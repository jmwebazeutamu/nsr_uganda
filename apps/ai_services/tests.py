"""ADR-0045 — AI services.

Written to pin the properties the ADR promises, not the implementation:
fail-closed switches, dual approval, one audit event per run, advisory-only,
and that a model can only name what its producer actually emits.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.ai_services import services as svc
from apps.ai_services.artifacts import (
    LinearScorer,
    ScoringError,
    checksum,
    dqa_payload_vocabulary,
)
from apps.ai_services.models import (
    AiFeature,
    AiModelVersion,
    AiRun,
    AiSuggestion,
    FeatureCode,
    FeatureState,
    ModelStatus,
)
from apps.ddup.models import DdupModelVersion, MatchPair, MergeAction, MergeDecision, PairStatus
from apps.ddup.tests import model_config
from apps.dqa.models import DqaResult
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db

SURNAME = "member.surname"
FIRST = "member.first_name"


@pytest.fixture
def ddup_model(db):
    return DdupModelVersion.objects.create(
        version=1, config=model_config(tier3={}), author="a", status="active",
    )


def linear(features=(SURNAME, FIRST), weights=(2.0, 2.0), intercept=-2.0):
    return {"kind": "linear", "features": list(features), "weights": list(weights),
            "intercept": intercept}


def robust(path="reported_household_size", agg="value", **kw):
    return {"kind": "robust_z", "threshold": kw.get("threshold", 3.5),
            "features": [{"name": "size", "path": path, "agg": agg,
                          "median": 5.0, "mad": 1.0}]}


def active_model(task, artifact, name="m", author="alice", approver="bob"):
    m = svc.register_model(name=name, task=task, owner="NSR Unit", artifact=artifact,
                           actor=author, validated_on=date(2026, 11, 1))
    svc.submit_model(m, actor=author)
    return svc.approve_model(m, approver=approver)


def advisory_ready(code, model, gate=None):
    svc.attach_model(code, model, actor="ops")
    svc.set_gate_config(code, gate or {"min_labelled_decisions": 1, "min_precision": 0.5,
                                       "score_cutoff": 0.5}, actor="ops")


def pair(ddup_model, a, b, scores=None, status=PairStatus.PENDING):
    return MatchPair.objects.create(
        record_type="member", record_a_id=a, record_b_id=b, tier=3, match_reason="probabilistic",
        per_field_scores=scores, model_version=ddup_model, status=status,
    )


# --- the kill switch fails closed ------------------------------------------


class TestFailsClosed:
    def test_master_switch_off_means_off_even_when_the_row_says_advisory(self, ddup_model, settings):
        settings.AI_SERVICES_ENABLED = True
        m = active_model(FeatureCode.DDUP_RANK, linear())
        svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
        AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).update(state=FeatureState.ADVISORY)
        settings.AI_SERVICES_ENABLED = False
        assert svc.feature_state(FeatureCode.DDUP_RANK) == FeatureState.OFF

    def test_defaults_to_off_everywhere(self, settings):
        assert settings.AI_SERVICES_ENABLED is False
        assert svc.feature_state(FeatureCode.DDUP_RANK) == FeatureState.OFF

    def test_no_row_is_off(self, enabled):
        assert svc.feature_state(FeatureCode.DQA_ANOMALY) == FeatureState.OFF

    def test_retiring_the_model_turns_the_feature_off(self, enabled, ddup_model):
        m = active_model(FeatureCode.DDUP_RANK, linear())
        svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="measure")
        assert svc.feature_state(FeatureCode.DDUP_RANK) == FeatureState.SHADOW
        svc.retire_model(m, actor="ops", reason="bad drift")
        assert svc.feature_state(FeatureCode.DDUP_RANK) == FeatureState.OFF

    def test_cannot_leave_off_without_the_master_switch(self, settings, ddup_model):
        settings.AI_SERVICES_ENABLED = True
        m = active_model(FeatureCode.DDUP_RANK, linear())
        svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
        settings.AI_SERVICES_ENABLED = False
        with pytest.raises(svc.AiDisabledError):
            svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="x")

    def test_off_is_always_allowed(self, settings):
        settings.AI_SERVICES_ENABLED = False
        row = svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.OFF, actor="ops", reason="incident")
        assert row.state == FeatureState.OFF

    def test_a_state_change_needs_a_reason(self, enabled):
        with pytest.raises(svc.GateError):
            svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.OFF, actor="ops", reason="")

    def test_nothing_runs_when_off(self, ddup_model):
        with pytest.raises(svc.AiDisabledError):
            svc.load_scorer(FeatureCode.DDUP_RANK)
        assert AiRun.objects.count() == 0


# --- the registry ----------------------------------------------------------


class TestRegistry:
    def test_approver_must_differ_from_author(self, ddup_model):
        m = svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="o", artifact=linear(),
                               actor="alice", validated_on=date(2026, 11, 1))
        svc.submit_model(m, actor="alice")
        with pytest.raises(svc.ModelLifecycleError, match="differ from author"):
            svc.approve_model(m, approver="alice")

    def test_a_model_needs_an_owner_and_a_validation_date(self, ddup_model):
        with pytest.raises(svc.ModelLifecycleError, match="owner"):
            svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="", artifact=linear(), actor="a")
        m = svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="o", artifact=linear(), actor="a")
        with pytest.raises(svc.ModelLifecycleError, match="validation date"):
            svc.submit_model(m, actor="a")

    def test_an_edited_artifact_cannot_be_approved_or_loaded(self, enabled, ddup_model):
        m = svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="o", artifact=linear(),
                               actor="alice", validated_on=date(2026, 11, 1))
        svc.submit_model(m, actor="alice")
        AiModelVersion.objects.filter(pk=m.pk).update(artifact=linear(weights=(9.0, 9.0)))
        m.refresh_from_db()
        with pytest.raises(svc.ModelLifecycleError, match="checksum"):
            svc.approve_model(m, approver="bob")

        good = active_model(FeatureCode.DDUP_RANK, linear(), name="g")
        svc.attach_model(FeatureCode.DDUP_RANK, good, actor="ops")
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="x")
        AiModelVersion.objects.filter(pk=good.pk).update(artifact=linear(weights=(9.0, 9.0)))
        with pytest.raises(svc.ModelLifecycleError, match="checksum"):
            svc.load_scorer(FeatureCode.DDUP_RANK)

    def test_approving_a_new_version_retires_the_old_one(self, ddup_model):
        v1 = active_model(FeatureCode.DDUP_RANK, linear(), name="rank")
        v2 = active_model(FeatureCode.DDUP_RANK, linear(weights=(1.0, 1.0)), name="rank")
        v1.refresh_from_db()
        assert (v1.status, v2.status, v2.version) == (ModelStatus.RETIRED, ModelStatus.ACTIVE, 2)

    def test_attaching_a_new_model_drops_advisory_back_to_shadow(self, enabled, ddup_model):
        v1 = active_model(FeatureCode.DDUP_RANK, linear(), name="rank")
        advisory_ready(FeatureCode.DDUP_RANK, v1)
        AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).update(state=FeatureState.ADVISORY)
        v2 = active_model(FeatureCode.DDUP_RANK, linear(weights=(1.0, 1.0)), name="rank")
        row = svc.attach_model(FeatureCode.DDUP_RANK, v2, actor="ops")
        assert row.state == FeatureState.SHADOW

    def test_a_model_cannot_serve_another_features_task(self, ddup_model):
        m = active_model(FeatureCode.DDUP_RANK, linear())
        with pytest.raises(svc.ModelLifecycleError):
            svc.attach_model(FeatureCode.DQA_ANOMALY, m, actor="ops")


# --- vocabulary: a model names only what its producer emits (D8) ------------


class TestVocabulary:
    """Each test asserts against the real producer, not a copy of it."""

    def test_ddup_ranker_may_name_the_active_tier3_features(self, ddup_model):
        active_model(FeatureCode.DDUP_RANK, linear())

    def test_ddup_ranker_naming_an_unknown_feature_is_refused(self, ddup_model):
        with pytest.raises(svc.ModelLifecycleError, match="member.nickname"):
            svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="o", actor="a",
                               artifact=linear(features=("member.nickname", FIRST)))

    def test_ddup_feature_names_are_the_keys_pairs_actually_carry(self, ddup_model):
        """Pin to the producer: the names in the active config are the keys
        discover_probabilistic_pairs writes to per_field_scores."""
        from apps.ai_services.artifacts import ddup_feature_vocabulary
        from apps.ddup.config import validate_ddup_configuration

        tier = validate_ddup_configuration(ddup_model.config).tiers["tier3"]
        assert ddup_feature_vocabulary() == {f["field"] for f in tier["features"]}

    def test_ddup_validation_refuses_when_there_is_no_active_model(self, db):
        with pytest.raises(svc.ModelLifecycleError, match="no active DDUP"):
            svc.register_model(name="m", task=FeatureCode.DDUP_RANK, owner="o", artifact=linear(), actor="a")

    def test_dqa_paths_must_exist_in_the_real_payload(self, db):
        top, member = dqa_payload_vocabulary()
        assert "reported_household_size" in top and "age" in member
        svc.register_model(name="a", task=FeatureCode.DQA_ANOMALY, owner="o", actor="a", artifact=robust())
        svc.register_model(name="b", task=FeatureCode.DQA_ANOMALY, owner="o", actor="a",
                           artifact=robust(path="members.*.age", agg="max"))
        for bad in (robust(path="household_size"), robust(path="members.*.age_years", agg="max"),
                    robust(path="members.*.age", agg="value"), robust(agg="max")):
            with pytest.raises(svc.ModelLifecycleError):
                svc.register_model(name="c", task=FeatureCode.DQA_ANOMALY, owner="o", actor="a", artifact=bad)

    def test_a_zero_mad_is_refused_rather_than_divided_by(self, db):
        bad = robust()
        bad["features"][0]["mad"] = 0
        with pytest.raises(svc.ModelLifecycleError, match="mad"):
            svc.register_model(name="m", task=FeatureCode.DQA_ANOMALY, owner="o", actor="a", artifact=bad)

    def test_a_missing_feature_raises_instead_of_scoring_zero(self):
        scorer = LinearScorer.from_artifact(linear())
        with pytest.raises(ScoringError):
            scorer.score({SURNAME: 0.9})


# --- promotion gate (D6) ----------------------------------------------------


class TestGate:
    def test_advisory_is_refused_while_the_gate_is_unset(self, enabled, ddup_model):
        m = active_model(FeatureCode.DDUP_RANK, linear())
        svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
        with pytest.raises(svc.GateError, match="gate_config not set"):
            svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.ADVISORY, actor="ops", reason="x")

    def test_a_gate_config_must_name_every_threshold(self, db):
        with pytest.raises(svc.GateError):
            svc.set_gate_config(FeatureCode.DDUP_RANK, {"min_precision": 0.9}, actor="ops")

    def test_advisory_needs_enough_labelled_decisions_at_the_precision(self, enabled, ddup_model):
        m = active_model(FeatureCode.DDUP_RANK, linear())
        advisory_ready(FeatureCode.DDUP_RANK, m, {"min_labelled_decisions": 2, "min_precision": 0.9,
                                                  "score_cutoff": 0.5})
        p1 = pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        p2 = pair(ddup_model, "A2", "B2", {SURNAME: 1.0, FIRST: 1.0})
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="x")
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        rank_pending_pairs()
        with pytest.raises(svc.GateError, match="0 labelled"):
            svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.ADVISORY, actor="ops", reason="x")

        MergeDecision.objects.create(match_pair=p1, action=MergeAction.MERGE, decided_by="r")
        MergeDecision.objects.create(match_pair=p2, action=MergeAction.REJECT, decided_by="r")
        with pytest.raises(svc.GateError, match="precision 0.500"):
            svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.ADVISORY, actor="ops", reason="x")

        MergeDecision.objects.filter(match_pair=p2).update(action=MergeAction.MERGE)
        row = svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.ADVISORY, actor="ops", reason="x")
        assert row.state == FeatureState.ADVISORY

    def test_hold_and_cross_household_are_not_labels(self, enabled, ddup_model):
        m = active_model(FeatureCode.DDUP_RANK, linear())
        advisory_ready(FeatureCode.DDUP_RANK, m)
        p = pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="x")
        from apps.ai_services.ddup_ranking import evaluate, rank_pending_pairs

        rank_pending_pairs()
        MergeDecision.objects.create(match_pair=p, action=MergeAction.ON_HOLD, decided_by="r")
        assert evaluate().labelled == 0

    def test_dqa_anomaly_cannot_be_promoted_without_a_disposition_record(self, enabled, db):
        m = active_model(FeatureCode.DQA_ANOMALY, robust())
        advisory_ready(FeatureCode.DQA_ANOMALY, m)
        with pytest.raises(svc.GateError, match="nothing to evaluate"):
            svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.ADVISORY, actor="ops", reason="x")


# --- DDUP ranking: advisory only, one audit event per run -------------------


@pytest.fixture
def shadow_ranker(enabled, ddup_model):
    m = active_model(FeatureCode.DDUP_RANK, linear())
    svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
    svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="measure")
    return m


class TestDdupRanking:
    def test_one_audit_event_per_run_however_many_pairs(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        for i in range(25):
            pair(ddup_model, f"A{i:02}", f"B{i:02}", {SURNAME: 0.9, FIRST: 0.9})
        before = AuditEvent.objects.filter(action="ai.inference.batch").count()
        run = rank_pending_pairs(actor="celery")
        events = AuditEvent.objects.filter(action="ai.inference.batch")
        assert events.count() - before == 1
        ev = events.get(entity_id=run.id)
        assert ev.field_changes["scored"] == 25 and ev.field_changes["feature"] == "ddup.rank"
        assert run.suggestions.count() == 25

    def test_the_audit_payload_carries_no_subject_identifiers(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        p = pair(ddup_model, "AAAAAAAAAAAAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBBBBBBBBBBBB",
                 {SURNAME: 1.0, FIRST: 1.0})
        run = rank_pending_pairs()
        ev = AuditEvent.objects.get(action="ai.inference.batch", entity_id=run.id)
        assert p.id not in str(ev.field_changes) and "AAAAAAAAAAAA" not in str(ev.field_changes)

    def test_it_never_changes_a_pair_or_decides_one(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        p = pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        p.refresh_from_db()
        assert p.status == PairStatus.PENDING and not MergeDecision.objects.exists()

    def test_pairs_without_features_are_skipped_not_scored_zero(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        pair(ddup_model, "A1", "B1", None)
        pair(ddup_model, "A2", "B2", {SURNAME: 1.0})  # missing first_name
        pair(ddup_model, "A3", "B3", {SURNAME: 1.0, FIRST: 1.0})
        run = rank_pending_pairs()
        assert (run.scored, run.skipped) == (1, 2)

    def test_resolved_pairs_are_not_re_ranked(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0}, status=PairStatus.MERGED)
        assert rank_pending_pairs().scored == 0

    def test_a_higher_similarity_ranks_higher(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        hi = pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        lo = pair(ddup_model, "A2", "B2", {SURNAME: 0.2, FIRST: 0.2})
        run = rank_pending_pairs()
        s = {x.subject_id: x.score for x in run.suggestions.all()}
        assert s[hi.id] > s[lo.id]

    def test_off_writes_nothing(self, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        with pytest.raises(svc.AiDisabledError):
            rank_pending_pairs()
        assert AiSuggestion.objects.count() == 0 and AiRun.objects.count() == 0

    def test_suggestions_are_hidden_in_shadow_and_after_the_kill_switch(self, shadow_ranker, ddup_model):
        from apps.ai_services.ddup_ranking import rank_pending_pairs

        p = pair(ddup_model, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        show = lambda: svc.visible_suggestions(FeatureCode.DDUP_RANK, "match_pair", [p.id]).count()  # noqa: E731
        assert show() == 0
        AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).update(state=FeatureState.ADVISORY)
        assert show() == 1
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.OFF, actor="ops", reason="incident")
        assert show() == 0


# --- DQA anomaly: a flag is not a rule outcome ------------------------------


def household(hid, size, ages):
    members = [SimpleNamespace(id=f"{hid}-{i}", age=a) for i, a in enumerate(ages)]
    return SimpleNamespace(id=hid, reported_household_size=size,
                           members=SimpleNamespace(all=lambda m=members: m))


class TestDqaAnomaly:
    @pytest.fixture
    def shadow(self, enabled):
        m = active_model(FeatureCode.DQA_ANOMALY, robust())
        svc.attach_model(FeatureCode.DQA_ANOMALY, m, actor="ops")
        svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.SHADOW, actor="ops", reason="measure")

    def test_it_flags_the_outlier_and_only_the_outlier(self, shadow):
        from apps.ai_services.dqa_anomaly import score_households

        run = score_households([household("H1", 5, [30]), household("H2", 40, [30])])
        d = {s.subject_id: s.details for s in run.suggestions.all()}
        assert d["H1"]["flagged"] is False and d["H2"]["flagged"] is True

    def test_it_creates_no_dqa_outcome_and_no_dqa_flag_event(self, shadow):
        from apps.ai_services.dqa_anomaly import score_households

        score_households([household("H2", 40, [30])])
        assert not DqaResult.objects.exists()
        assert not AuditEvent.objects.filter(action__startswith="dqa.").exists()

    def test_a_household_with_no_computable_feature_is_skipped(self, shadow):
        from apps.ai_services.dqa_anomaly import score_households

        run = score_households([household("H3", None, [])])
        assert (run.scored, run.skipped) == (0, 1)

    def test_member_aggregation_reads_real_member_values(self, enabled):
        from apps.ai_services.dqa_anomaly import score_households

        m = active_model(FeatureCode.DQA_ANOMALY, robust(path="members.*.age", agg="max"))
        svc.attach_model(FeatureCode.DQA_ANOMALY, m, actor="ops")
        svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.SHADOW, actor="ops", reason="x")
        run = score_households([household("H4", 4, [3, 130])])
        assert run.suggestions.get().details["flagged"] is True


# --- audit contract (Definition of Done 4) ----------------------------------


def test_every_lifecycle_step_is_audited_in_order(enabled, ddup_model):
    m = active_model(FeatureCode.DDUP_RANK, linear())
    svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
    svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="measure")
    actions = list(
        AuditEvent.objects.filter(action__startswith="ai.").order_by("occurred_at")
        .values_list("action", flat=True)
    )
    assert actions == ["ai.model.registered", "ai.model.submitted", "ai.model.approved",
                       "ai.feature.model_attached", "ai.feature.state_changed"]
    approved = AuditEvent.objects.get(action="ai.model.approved")
    assert approved.actor_id == "bob" and approved.field_changes["author"] == "alice"
    assert approved.field_changes["artifact_sha256"] == checksum(linear())


def test_ai_events_fit_the_audit_action_column(db):
    longest = max(len(a) for a in ("ai.feature.model_attached", "ai.inference.batch",
                                   "ai.feature.state_changed", "ai.model.registered"))
    assert longest <= AuditEvent._meta.get_field("action").max_length
