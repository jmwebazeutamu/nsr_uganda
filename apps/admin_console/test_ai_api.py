"""Admin Console · AI oversight API (ADR-0045).

Run through the real URL conf and session auth. The tests that matter most
here are the ones that pin what the endpoint must NOT do: show reviewers a
shadow suggestion, copy a reviewer's decision, or accept a write.
"""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai_services import services as svc
from apps.ai_services.ddup_ranking import rank_pending_pairs
from apps.ai_services.models import AiFeature, FeatureCode, FeatureState
from apps.ai_services.tests import active_model, linear, pair  # noqa: F401
from apps.ddup.models import DdupModelVersion, MergeAction, MergeDecision
from apps.ddup.tests import model_config

pytestmark = pytest.mark.django_db

OVERVIEW = "/api/v1/admin/ai/overview/"
SUGGESTIONS = "/api/v1/admin/ai/suggestions/"
SURNAME, FIRST = "member.surname", "member.first_name"


@pytest.fixture
def admin():
    u = get_user_model().objects.create_user("root", password="x", is_superuser=True, is_staff=True)
    c = APIClient()
    c.force_authenticate(u)
    return c


@pytest.fixture
def shadow_ranker(settings, db):
    settings.AI_SERVICES_ENABLED = True
    ddup = DdupModelVersion.objects.create(version=1, config=model_config(tier3={}), author="a", status="active")
    m = active_model(FeatureCode.DDUP_RANK, linear())
    svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
    svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="measure")
    return ddup


class TestAccess:
    def test_anonymous_and_ordinary_users_are_refused(self, db):
        assert APIClient().get(OVERVIEW).status_code in (401, 403)
        u = get_user_model().objects.create_user("clerk", password="x")
        c = APIClient()
        c.force_authenticate(u)
        for url in (OVERVIEW, f"{SUGGESTIONS}?feature=ddup.rank"):
            assert c.get(url).status_code == 403

    def test_it_is_read_only(self, admin):
        for url in (OVERVIEW, SUGGESTIONS):
            for method in ("post", "put", "patch", "delete"):
                assert getattr(admin, method)(url, {}).status_code == 405


class TestOverview:
    def test_everything_is_off_by_default(self, admin):
        body = admin.get(OVERVIEW).json()
        assert body["master_enabled"] is False
        assert [f["code"] for f in body["features"]] == list(FeatureCode.values)
        for f in body["features"]:
            assert f["effective_state"]["code"] == "off" and f["shown_to_reviewers"] is False
            assert f["model"] is None and f["last_run"] is None and f["gate_config"] == {}

    def test_labels_and_tones_come_from_the_server(self, admin):
        f = admin.get(OVERVIEW).json()["features"][0]
        assert f["label"] == FeatureCode.DDUP_RANK.label
        assert f["effective_state"] == {"code": "off", "label": "Off", "tone": "neutral"}

    def test_every_state_has_a_tone_and_it_is_a_real_ui_tone_code(self):
        from apps.admin_console.ai_api import STATE_TONE
        from apps.reference_data.models import ChoiceOption

        assert set(STATE_TONE) == set(FeatureState)
        codes = set(ChoiceOption.objects.filter(choice_list__list_name="ui_tone").values_list("code", flat=True))
        if not codes:
            pytest.skip("ui_tone is not seeded in this database")
        assert set(STATE_TONE.values()) <= codes

    def test_stored_and_effective_state_can_differ(self, admin, shadow_ranker, settings):
        settings.AI_SERVICES_ENABLED = False
        f = admin.get(OVERVIEW).json()["features"][0]
        assert f["stored_state"]["code"] == "shadow" and f["effective_state"]["code"] == "off"

    def test_it_reports_the_model_and_the_evaluation(self, admin, shadow_ranker):
        f = admin.get(OVERVIEW).json()["features"][0]
        assert f["model"]["owner"] == "NSR Unit" and f["model"]["validated_on"] == date(2026, 11, 1).isoformat()
        assert f["evaluation"]["meets_gate"] is False and f["evaluation"]["reasons"]

    def test_the_dqa_feature_says_why_it_cannot_be_evaluated(self, admin):
        dqa = admin.get(OVERVIEW).json()["features"][1]
        assert any("nothing to evaluate" in r for r in dqa["evaluation"]["reasons"])


class TestSuggestions:
    def test_an_unknown_feature_is_a_400(self, admin):
        assert admin.get(f"{SUGGESTIONS}?feature=nope").status_code == 400
        assert admin.get(SUGGESTIONS).status_code == 400

    def test_with_no_run_it_returns_an_empty_list(self, admin):
        body = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()
        assert body["results"] == [] and body["run"] is None and body["total"] == 0

    def test_shadow_suggestions_are_shown_here_but_flagged_hidden_from_reviewers(self, admin, shadow_ranker):
        pair(shadow_ranker, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        body = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()
        assert body["total"] == 1 and body["shown_to_reviewers"] is False
        assert body["run"]["state"] == "shadow"

    def test_the_reviewer_surface_still_hides_what_this_one_shows(self, admin, shadow_ranker):
        p = pair(shadow_ranker, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        assert admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()["total"] == 1
        assert svc.visible_suggestions(FeatureCode.DDUP_RANK, "match_pair", [p.id]).count() == 0
        AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).update(state=FeatureState.ADVISORY)
        body = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()
        assert body["shown_to_reviewers"] is True
        assert svc.visible_suggestions(FeatureCode.DDUP_RANK, "match_pair", [p.id]).count() == 1

    def test_highest_score_first_and_limit_is_applied(self, admin, shadow_ranker):
        for i, s in enumerate((0.2, 1.0, 0.6)):
            pair(shadow_ranker, f"A{i}", f"B{i}", {SURNAME: s, FIRST: s})
        rank_pending_pairs()
        body = admin.get(f"{SUGGESTIONS}?feature=ddup.rank&limit=2").json()
        scores = [r["score"] for r in body["results"]]
        assert len(scores) == 2 and scores == sorted(scores, reverse=True) and body["total"] == 3

    def test_limit_is_clamped(self, admin, shadow_ranker):
        assert admin.get(f"{SUGGESTIONS}?feature=ddup.rank&limit=99999").status_code == 200
        assert admin.get(f"{SUGGESTIONS}?feature=ddup.rank&limit=abc").status_code == 400

    def test_the_reviewer_outcome_is_read_from_the_decision_not_copied(self, admin, shadow_ranker):
        p = pair(shadow_ranker, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        first = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()["results"][0]
        assert first["reviewer_outcome"] is None
        MergeDecision.objects.create(match_pair=p, action=MergeAction.REJECT, decided_by="r")
        again = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()["results"][0]
        assert again["reviewer_outcome"] == {"code": "reject", "label": "Reject"}

    def test_the_payload_carries_ids_and_scores_not_personal_data(self, admin, shadow_ranker):
        pair(shadow_ranker, "A1", "B1", {SURNAME: 1.0, FIRST: 1.0})
        rank_pending_pairs()
        row = admin.get(f"{SUGGESTIONS}?feature=ddup.rank").json()["results"][0]
        assert set(row) == {"id", "subject_type", "subject_id", "score", "details",
                            "reviewer_outcome", "subject_status"}
