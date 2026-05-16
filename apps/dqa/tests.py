"""DQA engine + approval workflow tests.

Covers:
- Each of the three Sprint 0 wired rules (AC-MANDATORY*, AC-NIN-FORMAT,
  AC-GPS-ACCURACY) at the pass and fail boundary.
- The author != approved_by constraint at the service layer.
- Unknown operator raises DSLError.

References:
- SAD §4.2 acceptance criteria
- CLAUDE.md "Tests first for any change touching ... DAT-DQA"
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.dqa.engine import DSLError, evaluate, evaluate_expression
from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.dqa.services import (
    ApprovalError,
    approve,
    reject,
    retire,
    submit_for_approval,
)
from apps.security.models import AuditEvent

# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def draft_rule(db):
    return DqaRule.objects.create(
        rule_id="TEST-RULE",
        version=1,
        description="for tests",
        severity=Severity.BLOCKING,
        expression={"field": "surname", "op": "not_null"},
        error_message_template="missing",
        applicability_filter={"entity": "member"},
        effective_from=date(2026, 1, 1),
        author="alice",
    )


# --- Engine: AC-MANDATORY ---------------------------------------------------

class TestMandatory:
    def test_passes_when_fields_present(self):
        expr = {"all_of": [
            {"field": "surname", "op": "not_null"},
            {"field": "first_name", "op": "not_null"},
        ]}
        assert evaluate_expression(expr, {"surname": "Okot", "first_name": "James"}) is True

    def test_fails_when_field_missing(self):
        expr = {"all_of": [
            {"field": "surname", "op": "not_null"},
            {"field": "first_name", "op": "not_null"},
        ]}
        assert evaluate_expression(expr, {"surname": "Okot", "first_name": ""}) is False
        assert evaluate_expression(expr, {"surname": "Okot"}) is False


# --- Engine: AC-NIN-FORMAT --------------------------------------------------

class TestNinFormat:
    PATTERN = r"^(CM|CF)[A-Z0-9]{12}$"

    @pytest.mark.parametrize("nin", [
        "CM1234567890AB",
        "CFABCDEFGHIJKL",
        "CM00000000000A",
    ])
    def test_passes_valid(self, nin):
        expr = {"field": "nin", "op": "regex", "value": self.PATTERN}
        assert evaluate_expression(expr, {"nin": nin}) is True

    @pytest.mark.parametrize("nin", [
        "CM12345",                # too short
        "XM12345678901A",         # wrong prefix
        "cm1234567890ab",         # lowercase
        "CM12345 67890AB",        # whitespace
        "",                       # empty
    ])
    def test_fails_invalid(self, nin):
        expr = {"field": "nin", "op": "regex", "value": self.PATTERN}
        assert evaluate_expression(expr, {"nin": nin}) is False

    def test_passes_when_optional_field_missing(self):
        # The seeded rule uses any_of(is_null, regex_match) so a NULL NIN passes.
        expr = {"any_of": [
            {"field": "nin", "op": "is_null"},
            {"field": "nin", "op": "regex", "value": self.PATTERN},
        ]}
        assert evaluate_expression(expr, {"nin": None}) is True


# --- Engine: AC-GPS-ACCURACY ------------------------------------------------

class TestGpsAccuracy:
    @pytest.mark.parametrize("accuracy", [0, 5, 9.99, 10])
    def test_passes_within_threshold(self, accuracy):
        expr = {"field": "acc", "op": "le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is True

    @pytest.mark.parametrize("accuracy", [10.01, 15, 100])
    def test_fails_above_threshold(self, accuracy):
        expr = {"field": "acc", "op": "le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is False

    def test_passes_when_gps_missing_via_any_of(self):
        expr = {"any_of": [
            {"field": "acc", "op": "is_null"},
            {"field": "acc", "op": "le", "value": 10},
        ]}
        assert evaluate_expression(expr, {"acc": None}) is True


# --- Engine: error paths ----------------------------------------------------

class TestEngineErrors:
    def test_unknown_operator_raises(self):
        with pytest.raises(DSLError):
            evaluate_expression({"field": "x", "op": "weird_op", "value": 1}, {"x": 1})

    def test_all_of_requires_list(self):
        with pytest.raises(DSLError):
            evaluate_expression({"all_of": "not-a-list"}, {})


# --- Engine: full evaluate() ------------------------------------------------

class TestEvaluateProducesResult:
    def test_pass_produces_empty_reason(self, draft_rule):
        ev = evaluate(draft_rule, {"surname": "Okot"}, record_type="member", record_id="m-1")
        assert ev.passed is True
        assert ev.reason == ""

    def test_fail_renders_reason(self, draft_rule):
        ev = evaluate(draft_rule, {"surname": ""}, record_type="member", record_id="m-1")
        assert ev.passed is False
        assert "missing" in ev.reason


# --- Approval workflow: author != approver ----------------------------------

class TestApprovalWorkflow:
    def test_full_flow(self, draft_rule):
        assert draft_rule.status == RuleStatus.DRAFT
        submit_for_approval(draft_rule)
        assert draft_rule.status == RuleStatus.PENDING_APPROVAL
        approve(draft_rule, approver="bob", note="ok")
        assert draft_rule.status == RuleStatus.ACTIVE
        assert draft_rule.approved_by == "bob"
        assert draft_rule.approved_at is not None

    def test_author_cannot_approve_own_rule(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="cannot approve"):
            approve(draft_rule, approver=draft_rule.author, note="not relevant")

    def test_cannot_approve_a_draft(self, draft_rule):
        with pytest.raises(ApprovalError, match="PENDING_APPROVAL"):
            approve(draft_rule, approver="bob", note="ok")

    def test_cannot_approve_without_approver(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="approver must be supplied"):
            approve(draft_rule, approver="", note="ok")


# --- DQA-2: lifecycle fields, audit emission, note/reason persistence -------

class TestLifecycleFields:
    def test_new_rule_has_empty_lifecycle_audit_fields(self, draft_rule):
        assert draft_rule.approval_note == ""
        assert draft_rule.rejection_reason == ""
        assert draft_rule.submitted_at is None

    def test_submit_sets_submitted_at(self, draft_rule):
        submit_for_approval(draft_rule)
        draft_rule.refresh_from_db()
        assert draft_rule.submitted_at is not None

    def test_approve_persists_note(self, draft_rule):
        submit_for_approval(draft_rule)
        approve(draft_rule, approver="bob",
                note="matches AC-MANDATORY for member surname")
        draft_rule.refresh_from_db()
        assert draft_rule.approval_note == "matches AC-MANDATORY for member surname"

    def test_approve_rejects_blank_note(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="note"):
            approve(draft_rule, approver="bob", note="")
        with pytest.raises(ApprovalError, match="note"):
            approve(draft_rule, approver="bob", note="   ")

    def test_reject_persists_reason(self, draft_rule):
        submit_for_approval(draft_rule)
        reject(draft_rule, approver="bob",
               reason="expression conflicts with AC-NIN-FORMAT")
        draft_rule.refresh_from_db()
        assert draft_rule.rejection_reason == "expression conflicts with AC-NIN-FORMAT"
        assert draft_rule.status == RuleStatus.REJECTED

    def test_reject_requires_non_blank_reason(self, draft_rule):
        submit_for_approval(draft_rule)
        with pytest.raises(ApprovalError, match="reason"):
            reject(draft_rule, approver="bob", reason="")
        with pytest.raises(ApprovalError, match="reason"):
            reject(draft_rule, approver="bob", reason="   ")


class TestAuditEmission:
    """One AuditEvent per successful transition; none on failed transitions.
    entity_type="dqa.rule"; entity_id=rule.id (ULID); action names
    namespaced under dqa.rule_version.<verb>; field_changes carries
    before/after plus note/reason payload where applicable.
    """

    def _by_action(self, rule_id, action):
        return AuditEvent.objects.filter(
            entity_type="dqa.rule", entity_id=rule_id, action=action,
        )

    def test_submit_emits_one_event(self, draft_rule):
        before = AuditEvent.objects.count()
        submit_for_approval(draft_rule, actor="alice")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.submitted_for_approval",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "alice"
        assert ev.field_changes["before"] == RuleStatus.DRAFT
        assert ev.field_changes["after"] == RuleStatus.PENDING_APPROVAL

    def test_approve_emits_one_event_with_note(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before = AuditEvent.objects.count()
        approve(draft_rule, approver="bob", note="ok",
                actor="bob")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.approved",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "bob"
        assert ev.field_changes["approver"] == "bob"
        assert ev.field_changes["note"] == "ok"
        assert ev.field_changes["after"] == RuleStatus.ACTIVE

    def test_reject_emits_one_event_with_reason(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before = AuditEvent.objects.count()
        reject(draft_rule, approver="bob",
               reason="conflicts with AC-NIN-FORMAT", actor="bob")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.rejected",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.field_changes["reason"] == "conflicts with AC-NIN-FORMAT"
        assert ev.field_changes["after"] == RuleStatus.REJECTED

    def test_retire_emits_one_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        approve(draft_rule, approver="bob", note="ok", actor="bob")
        before = AuditEvent.objects.count()
        retire(draft_rule, actor="carol")
        assert AuditEvent.objects.count() == before + 1
        ev = self._by_action(
            draft_rule.id, "dqa.rule_version.retired",
        ).order_by("-occurred_at").first()
        assert ev is not None
        assert ev.actor_id == "carol"
        assert ev.field_changes["after"] == RuleStatus.RETIRED

    def test_failed_transition_emits_no_event(self, draft_rule):
        # Draft → approve must raise; no audit row should land.
        before = AuditEvent.objects.count()
        with pytest.raises(ApprovalError):
            approve(draft_rule, approver="bob", note="ok")
        assert AuditEvent.objects.count() == before

    def test_blank_note_failure_emits_no_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before_count = AuditEvent.objects.count()
        with pytest.raises(ApprovalError):
            approve(draft_rule, approver="bob", note="   ")
        assert AuditEvent.objects.count() == before_count

    def test_self_approval_attempt_emits_no_event(self, draft_rule):
        submit_for_approval(draft_rule, actor="alice")
        before_count = AuditEvent.objects.count()
        with pytest.raises(ApprovalError, match="cannot approve"):
            approve(draft_rule, approver=draft_rule.author, note="trying")
        assert AuditEvent.objects.count() == before_count


# --- DQA-3 / US-079: remaining operators ------------------------------------

class TestAccuracyLe:
    """`accuracy_le` — explicit semantic for GPS accuracy rules.
    Equivalent to `le` numerically; named so the Rule Editor can offer
    it specifically on geometry fields without ambiguity."""

    @pytest.mark.parametrize("accuracy", [0, 5, 9.99, 10])
    def test_passes_within_threshold(self, accuracy):
        expr = {"field": "acc", "op": "accuracy_le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is True

    @pytest.mark.parametrize("accuracy", [10.01, 15, 100])
    def test_fails_above_threshold(self, accuracy):
        expr = {"field": "acc", "op": "accuracy_le", "value": 10}
        assert evaluate_expression(expr, {"acc": accuracy}) is False

    def test_fails_on_null(self):
        # Unlike is_null/any_of patterns elsewhere, this op alone
        # treats missing accuracy as a failure — operators wanting
        # "missing or under N" wrap with any_of.
        expr = {"field": "acc", "op": "accuracy_le", "value": 10}
        assert evaluate_expression(expr, {"acc": None}) is False


class TestCountOps:
    """`count_eq` / `count_neq` — for list-shaped fields like roster."""

    def test_count_eq_matches_list_length(self):
        expr = {"field": "members", "op": "count_eq", "value": 3}
        assert evaluate_expression(expr, {"members": [1, 2, 3]}) is True
        assert evaluate_expression(expr, {"members": [1, 2]}) is False

    def test_count_neq_inverts(self):
        expr = {"field": "members", "op": "count_neq", "value": 0}
        assert evaluate_expression(expr, {"members": [1]}) is True
        assert evaluate_expression(expr, {"members": []}) is False

    def test_count_eq_on_non_list_is_false(self):
        # A scalar can't have a count; rule should fail rather than
        # crash so the operator gets a clear validation failure.
        expr = {"field": "members", "op": "count_eq", "value": 1}
        assert evaluate_expression(expr, {"members": "not-a-list"}) is False

    def test_count_eq_on_none_is_false(self):
        expr = {"field": "members", "op": "count_eq", "value": 0}
        assert evaluate_expression(expr, {"members": None}) is False


class TestCrossFieldEq:
    """`cross_field_eq` — leaf with left_field + right_field.
    Used for rules like "household.head_id matches a member.line_number=1
    on the same household."""

    def test_passes_when_two_fields_match(self):
        expr = {
            "op": "cross_field_eq",
            "left_field": "head_name", "right_field": "primary_contact",
        }
        rec = {"head_name": "Nakato Sarah", "primary_contact": "Nakato Sarah"}
        assert evaluate_expression(expr, rec) is True

    def test_fails_when_two_fields_differ(self):
        expr = {
            "op": "cross_field_eq",
            "left_field": "head_name", "right_field": "primary_contact",
        }
        rec = {"head_name": "Nakato Sarah", "primary_contact": "Okot James"}
        assert evaluate_expression(expr, rec) is False

    def test_both_none_passes(self):
        # If both sides are missing, equality holds; operator wanting
        # "both present AND equal" composes with not_null.
        expr = {
            "op": "cross_field_eq",
            "left_field": "a", "right_field": "b",
        }
        assert evaluate_expression(expr, {}) is True

    def test_requires_left_and_right_field_keys(self):
        with pytest.raises(DSLError, match="cross_field_eq"):
            evaluate_expression({"op": "cross_field_eq", "field": "x"}, {})


class TestReferencesExisting:
    """`references_existing` — the field's value must resolve to a row
    in the named Django model. Uses dot-notation `app_label.ModelName`
    to avoid hard-coding which model. Returns False on bad lookups
    rather than raising — the rule should report the data-quality
    failure, not crash the pipeline."""

    def test_passes_when_geographic_unit_exists(self, db):
        from datetime import date as _d

        from apps.reference_data.models import GeographicUnit
        g = GeographicUnit.objects.create(
            level="parish", code="REF-OK-1", name="Ref OK",
            effective_from=_d(2026, 1, 1),
        )
        expr = {
            "field": "parish_id", "op": "references_existing",
            "value": "reference_data.GeographicUnit",
        }
        assert evaluate_expression(expr, {"parish_id": g.id}) is True

    def test_fails_when_lookup_does_not_exist(self, db):
        expr = {
            "field": "parish_id", "op": "references_existing",
            "value": "reference_data.GeographicUnit",
        }
        assert evaluate_expression(expr, {"parish_id": 999999999}) is False

    def test_fails_on_unknown_model(self):
        expr = {
            "field": "parish_id", "op": "references_existing",
            "value": "nonexistent.Model",
        }
        # Unknown model → False (rule reports failure); never raises.
        assert evaluate_expression(expr, {"parish_id": 1}) is False

    def test_fails_on_null_field_value(self):
        expr = {
            "field": "parish_id", "op": "references_existing",
            "value": "reference_data.GeographicUnit",
        }
        assert evaluate_expression(expr, {"parish_id": None}) is False


class TestWithinPolygon:
    """`within_polygon` — point-in-polygon via GEOSGeometry.

    Uses Django's GIS bindings rather than a homegrown implementation.
    Polygon comes from the rule expression `value`; field value is a
    {lat, lng} dict or a WKT-style POINT string. SQLite doesn't have
    PostGIS but Django's in-process GEOS library is independent of
    the DB backend, so the operator works on every backend.
    """

    POLY_WKT = "POLYGON((0 0, 0 10, 10 10, 10 0, 0 0))"

    def test_inside_polygon_passes(self):
        expr = {
            "field": "gps", "op": "within_polygon",
            "value": self.POLY_WKT,
        }
        assert evaluate_expression(
            expr, {"gps": {"lat": 5, "lng": 5}},
        ) is True

    def test_outside_polygon_fails(self):
        expr = {
            "field": "gps", "op": "within_polygon",
            "value": self.POLY_WKT,
        }
        assert evaluate_expression(
            expr, {"gps": {"lat": 50, "lng": 50}},
        ) is False

    def test_accepts_wkt_point_string(self):
        expr = {
            "field": "gps", "op": "within_polygon",
            "value": self.POLY_WKT,
        }
        assert evaluate_expression(expr, {"gps": "POINT(2 2)"}) is True

    def test_null_field_fails(self):
        expr = {
            "field": "gps", "op": "within_polygon",
            "value": self.POLY_WKT,
        }
        assert evaluate_expression(expr, {"gps": None}) is False

    def test_invalid_polygon_raises_dsl_error(self):
        expr = {
            "field": "gps", "op": "within_polygon",
            "value": "NOT A POLYGON",
        }
        with pytest.raises(DSLError, match="polygon"):
            evaluate_expression(expr, {"gps": {"lat": 1, "lng": 1}})


# --- DQA-4 / US-077: preview endpoint + DqaRulePreviewRun -------------------

class TestPreviewEndpoint:
    """POST /api/v1/dqa/rules/{id}/preview/ with
    {sample_size, record_type}. Returns counts + up to 10 failed IDs.
    Never returns record values. Persists a DqaRulePreviewRun row."""

    URL_FMT = "/api/v1/dqa/rules/{id}/preview/"

    @pytest.fixture
    def _client(self, db, django_user_model):
        from rest_framework.test import APIClient
        u = django_user_model.objects.create_user(
            username="dqa-prev", password="p", is_superuser=True,
        )
        c = APIClient()
        c.force_authenticate(user=u)
        return c, u

    @pytest.fixture
    def _members(self, db):
        # Seed 12 members; surname missing on 4 → 4 expected failures.
        from datetime import date as _d

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"),
            ("district", "d", "sr"), ("county", "c", "d"),
            ("sub_county", "sc", "c"), ("parish", "p", "sc"),
            ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"PRV-{key.upper()}", name=key,
                parent=nodes.get(parent), effective_from=_d(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"],
            district=nodes["d"], county=nodes["c"],
            sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="rural",
        )
        out = []
        for i in range(12):
            out.append(Member.objects.create(
                household=hh, line_number=i + 1,
                surname="" if i % 3 == 0 else f"S{i}",
                first_name=f"F{i}", sex="M",
            ))
        return out

    def test_returns_counts_and_ids(self, _client, _members, draft_rule):
        client, _ = _client
        url = self.URL_FMT.format(id=draft_rule.id)
        r = client.post(url, {"sample_size": 50, "record_type": "member"},
                        format="json")
        assert r.status_code == 200, r.data
        assert "pass_count" in r.data
        assert "fail_count" in r.data
        assert "sample_failed_record_ids" in r.data
        # 4 of 12 fail surname not_null.
        assert r.data["pass_count"] + r.data["fail_count"] == 12
        assert r.data["fail_count"] == 4
        # IDs only, no values.
        for rid in r.data["sample_failed_record_ids"]:
            assert isinstance(rid, str) and len(rid) > 0

    def test_never_returns_record_values(
        self, _client, _members, draft_rule,
    ):
        client, _ = _client
        url = self.URL_FMT.format(id=draft_rule.id)
        r = client.post(url, {"sample_size": 50, "record_type": "member"},
                        format="json")
        assert r.status_code == 200
        # Response must NOT contain anything that looks like a name
        # or NIN — only IDs and counts. Cheap structural check.
        forbidden_keys = {"surname", "first_name", "nin_value", "telephone_1", "data"}
        assert forbidden_keys.isdisjoint(r.data.keys())
        # And the failed IDs list must not contain any rendered records.
        for v in r.data["sample_failed_record_ids"]:
            assert not isinstance(v, dict)

    def test_sample_ids_capped_at_10(self, _client, draft_rule):
        # 15 failing rows; preview must cap returned IDs at 10.
        from datetime import date as _d

        from apps.data_management.models import Household, Member
        from apps.reference_data.models import GeographicUnit
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"),
            ("district", "d", "sr"), ("county", "c", "d"),
            ("sub_county", "sc", "c"), ("parish", "p", "sc"),
            ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"CAP-{key.upper()}", name=key,
                parent=nodes.get(parent), effective_from=_d(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"],
            district=nodes["d"], county=nodes["c"],
            sub_county=nodes["sc"], parish=nodes["p"],
            village=nodes["v"], urban_rural="rural",
        )
        for i in range(15):
            Member.objects.create(
                household=hh, line_number=i + 1,
                surname="", first_name=f"F{i}", sex="M",
            )
        client, _ = _client
        url = self.URL_FMT.format(id=draft_rule.id)
        r = client.post(url, {"sample_size": 50, "record_type": "member"},
                        format="json")
        assert r.status_code == 200
        assert r.data["fail_count"] == 15
        assert len(r.data["sample_failed_record_ids"]) == 10

    def test_persists_a_preview_run_row(
        self, _client, _members, draft_rule,
    ):
        from apps.dqa.models import DqaRulePreviewRun
        client, u = _client
        url = self.URL_FMT.format(id=draft_rule.id)
        before = DqaRulePreviewRun.objects.count()
        r = client.post(url, {"sample_size": 50, "record_type": "member"},
                        format="json")
        assert r.status_code == 200
        after = DqaRulePreviewRun.objects.count()
        assert after == before + 1
        run = DqaRulePreviewRun.objects.order_by("-executed_at").first()
        assert run.rule_id == draft_rule.id
        assert run.executed_by == u.username
        assert run.pass_count == 8
        assert run.fail_count == 4
        assert isinstance(run.sample_failed_record_ids, list)
        assert len(run.sample_failed_record_ids) == 4

    def test_rejects_unknown_record_type(
        self, _client, _members, draft_rule,
    ):
        client, _ = _client
        url = self.URL_FMT.format(id=draft_rule.id)
        r = client.post(url, {"sample_size": 50, "record_type": "alien"},
                        format="json")
        assert r.status_code == 400


# --- DQA-5 / US-076: write endpoints + role gate ----------------------------

class TestWriteEndpoints:
    """ModelViewSet + role-gated create/update + lifecycle action endpoints.

    Layout per brief:
      POST   /api/v1/dqa/rules/                     create draft
      PUT    /api/v1/dqa/rules/{id}/                update draft
      POST   /api/v1/dqa/rules/{id}/submit-for-approval/
      POST   /api/v1/dqa/rules/{id}/approve/  { note }
      POST   /api/v1/dqa/rules/{id}/reject/   { reason }
      POST   /api/v1/dqa/rules/{id}/retire/
    """

    def _client(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _make_author(self, django_user_model, username="dqa-author"):
        from django.contrib.auth.models import Group
        user = django_user_model.objects.create_user(username=username, password="p")
        group, _ = Group.objects.get_or_create(name="dqa_author")
        user.groups.add(group)
        return user

    def test_non_author_cannot_create(self, db, django_user_model):
        # A logged-in user without the dqa_author group: 403 on create.
        outsider = django_user_model.objects.create_user(
            username="outsider", password="p",
        )
        r = self._client(outsider).post("/api/v1/dqa/rules/", {
            "rule_id": "NEW-RULE", "version": 1,
            "description": "x", "severity": "blocking",
            "expression": {"field": "surname", "op": "not_null"},
            "error_message_template": "x",
            "applicability_filter": {"entity": "member"},
            "author": "outsider",
        }, format="json")
        assert r.status_code == 403

    def test_author_can_create_draft(self, db, django_user_model):
        author = self._make_author(django_user_model, "alice")
        r = self._client(author).post("/api/v1/dqa/rules/", {
            "rule_id": "NEW-RULE", "version": 1,
            "description": "x", "severity": "blocking",
            "expression": {"field": "surname", "op": "not_null"},
            "error_message_template": "x",
            "applicability_filter": {"entity": "member"},
            "author": "alice",
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["status"] == "draft"

    def test_submit_endpoint_advances_to_pending(
        self, db, django_user_model, draft_rule,
    ):
        author = self._make_author(django_user_model, "alice")
        url = f"/api/v1/dqa/rules/{draft_rule.id}/submit-for-approval/"
        r = self._client(author).post(url, {}, format="json")
        assert r.status_code == 200
        draft_rule.refresh_from_db()
        assert draft_rule.status == "pending_approval"
        assert draft_rule.submitted_at is not None

    def test_approve_endpoint_requires_note(
        self, db, django_user_model, draft_rule,
    ):
        submit_for_approval(draft_rule)
        approver = self._make_author(django_user_model, "bob")
        url = f"/api/v1/dqa/rules/{draft_rule.id}/approve/"
        # Blank note → 400.
        r = self._client(approver).post(url, {"note": ""}, format="json")
        assert r.status_code == 400
        # Good note → 200 + ACTIVE.
        r = self._client(approver).post(
            url, {"note": "matches AC-MANDATORY"}, format="json",
        )
        assert r.status_code == 200
        draft_rule.refresh_from_db()
        assert draft_rule.status == "active"
        assert draft_rule.approval_note == "matches AC-MANDATORY"

    def test_reject_endpoint_requires_reason(
        self, db, django_user_model, draft_rule,
    ):
        submit_for_approval(draft_rule)
        approver = self._make_author(django_user_model, "bob")
        url = f"/api/v1/dqa/rules/{draft_rule.id}/reject/"
        r = self._client(approver).post(url, {"reason": ""}, format="json")
        assert r.status_code == 400
        r = self._client(approver).post(
            url, {"reason": "conflicts with X"}, format="json",
        )
        assert r.status_code == 200
        draft_rule.refresh_from_db()
        assert draft_rule.status == "rejected"
        assert draft_rule.rejection_reason == "conflicts with X"

    def test_approve_endpoint_blocks_self_approval(
        self, db, django_user_model, draft_rule,
    ):
        submit_for_approval(draft_rule)
        # alice is the rule's author per the fixture.
        self_approver = self._make_author(django_user_model, "alice")
        url = f"/api/v1/dqa/rules/{draft_rule.id}/approve/"
        r = self._client(self_approver).post(
            url, {"note": "trying to self-approve"}, format="json",
        )
        assert r.status_code == 400
        assert "cannot approve" in str(r.data).lower()

    def test_retire_endpoint_works_on_active(
        self, db, django_user_model, draft_rule,
    ):
        submit_for_approval(draft_rule)
        approver = self._make_author(django_user_model, "bob")
        self._client(approver).post(
            f"/api/v1/dqa/rules/{draft_rule.id}/approve/",
            {"note": "ok"}, format="json",
        )
        r = self._client(approver).post(
            f"/api/v1/dqa/rules/{draft_rule.id}/retire/", {}, format="json",
        )
        assert r.status_code == 200
        draft_rule.refresh_from_db()
        assert draft_rule.status == "retired"

    def test_endpoint_actions_emit_audit_rows(
        self, db, django_user_model, draft_rule,
    ):
        approver = self._make_author(django_user_model, "bob")
        before = AuditEvent.objects.filter(entity_type="dqa.rule").count()
        # submit + approve via the REST endpoints
        self._client(self._make_author(django_user_model, "alice")).post(
            f"/api/v1/dqa/rules/{draft_rule.id}/submit-for-approval/",
            {}, format="json",
        )
        self._client(approver).post(
            f"/api/v1/dqa/rules/{draft_rule.id}/approve/",
            {"note": "good"}, format="json",
        )
        after = AuditEvent.objects.filter(entity_type="dqa.rule").count()
        assert after == before + 2


# --- DQA-5 admin smoke tests ------------------------------------------------

class TestRuleEditorAdminSmoke:
    """The change_form view should render the v2 Rule Editor panels
    (preview, decisions, version history) when DQA_RULE_EDITOR_V2 is
    on. Cheap structural assertions only — exhaustive UI testing
    happens during the manual sanity check listed in the Definition
    of Done."""

    def _staff_client(self, db, django_user_model):
        from django.test import Client
        u = django_user_model.objects.create_user(
            username="dqa-staff", password="p",
            is_staff=True, is_superuser=True,
        )
        c = Client()
        c.force_login(u)
        return c

    def test_change_form_renders_v2_panels(
        self, db, django_user_model, draft_rule, settings,
    ):
        settings.DQA_RULE_EDITOR_V2 = True
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/dqa/dqarule/{draft_rule.id}/change/")
        assert r.status_code == 200
        body = r.content.decode()
        # The three v2 panels are present, identified by the marker ids
        # the template sets.
        assert 'id="dqa-preview-panel"' in body
        assert 'id="dqa-decisions-panel"' in body
        assert 'id="dqa-history-panel"' in body
        # And the wizard fields show in the admin form fieldset.
        assert "wizard_field" in body

    def test_change_form_omits_v2_panels_when_flag_off(
        self, db, django_user_model, draft_rule, settings,
    ):
        settings.DQA_RULE_EDITOR_V2 = False
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/dqa/dqarule/{draft_rule.id}/change/")
        assert r.status_code == 200
        body = r.content.decode()
        assert 'id="dqa-preview-panel"' not in body
        assert 'id="dqa-history-panel"' not in body

    def test_version_history_includes_unified_diff(
        self, db, django_user_model, settings,
    ):
        # Two versions of the same rule_id; v2's expression differs
        # → unified diff lands in the history pane.
        settings.DQA_RULE_EDITOR_V2 = True
        v1 = DqaRule.objects.create(
            rule_id="HIST-1", version=1,
            description="v1", severity=Severity.BLOCKING,
            expression={"field": "surname", "op": "not_null"},
            error_message_template="x", author="alice",
            applicability_filter={"entity": "member"},
            effective_from=date(2026, 1, 1),
        )
        v2 = DqaRule.objects.create(
            rule_id="HIST-1", version=2,
            description="v2", severity=Severity.BLOCKING,
            expression={"field": "first_name", "op": "not_null"},
            error_message_template="x", author="alice",
            applicability_filter={"entity": "member"},
            effective_from=date(2026, 2, 1),
        )
        c = self._staff_client(db, django_user_model)
        r = c.get(f"/admin/dqa/dqarule/{v2.id}/change/")
        body = r.content.decode()
        assert "dqa-diff" in body
        # diff markers showing the field swap
        assert "- " in body and "+ " in body
        # Both versions present in the history table
        assert "v1" in body and "v2" in body
        del v1  # used only as a fixture setup row
