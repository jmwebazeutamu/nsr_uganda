"""Re-run gates must work on a record sitting in the queue.

"Re-run gates" is the operator's remedy when a rule was wrong: correct
the rule, re-evaluate, and let the record route itself. That only holds
if a record can be re-checked *from the state it is already in* — a
record that has been through the gates once sits in IDV_PENDING,
DDUP_REVIEW, PENDING_PROMOTION or QUALITY_FAILED, not in the state it
was first processed from.

The existing tests cover the first pass and the terminal no-ops. These
cover the loop: process, change the rules, process again, and confirm
the record moves — including that the audit actor is the signed-in
session rather than anything the client sent.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.dqa.models import DqaRule, RuleStatus, Severity
from apps.ingestion_hub.connectors.kobo import kobo_to_canonical
from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
    StageRecord,
    StageRecordState,
)
from apps.ingestion_hub.services import (
    land_payload,
    process_stage_record,
    promote_stage_record,
    quarantine_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.reference_data.models import GeographicUnit
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db


def _member(index: int, relationship: str, **overrides) -> dict:
    row = {
        "member_index": index,
        "c1_full_name": f"Test Member{index}",
        "c2_relationship": relationship,
        "c4_sex": "2",
        "c6_age_years": "40",
        "c8_nin_status": "0",
    }
    row.update(overrides)
    return row


def _submission(members: list[dict]) -> dict:
    return {
        "a0_region": "REG", "a1_subregion": "SUB", "a2_district_city": "DIS",
        "a3_county_municipality": "CTY", "a4_subcounty_division_tc": "SCT",
        "a5_parish_ward": "PAR", "a6_lc1_village_cell": "VIL",
        "a7_rural_urban": "2", "hh_size": "1",
        "household_members": members,
    }


@pytest.fixture
def geo(db):
    derived = kobo_to_canonical(_submission([_member(1, "01")]))["geographic"]
    parent = None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        parent = GeographicUnit.objects.create(
            level=level, code=derived[level], name=derived[level],
            parent=parent, effective_from=date(2026, 1, 1),
        )
    return derived


@pytest.fixture
def connector(db):
    src = SourceSystem.objects.create(
        code="KOBO-RERUN", name="Kobo", kind=SourceSystemKind.KOBO,
    )
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-RERUN",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
    )
    return Connector.objects.create(source_system=src, name="kobo-rerun")


@pytest.fixture
def staged(geo, connector):
    """A clean household, staged but not yet processed."""
    raw = _submission([_member(1, "01"), _member(2, "02", c6_age_years="38")])
    run = start_connector_run(connector)
    landing = land_payload(run, raw)
    return stage_from_landing(landing, canonical_payload=kobo_to_canonical(raw))


def _blocking_rule(rule_id: str, *, field: str = "surname") -> DqaRule:
    """A member rule that fails whenever `field` is set — i.e. always."""
    return DqaRule.objects.create(
        rule_id=rule_id, version=1, status=RuleStatus.ACTIVE,
        approved_by="qa-lead", author="test",
        description="blocks everything", severity=Severity.BLOCK,
        expression={"op": "is_null", "field": field},
        error_message_template=f"{field} must be empty",
        applicability_filter={"entity": "member"},
    )


def test_a_record_blocked_by_a_wrong_rule_clears_when_the_rule_is_corrected(staged):
    """The whole point of the button: the record is not stuck with the
    verdict of a rule that has since been fixed."""
    rule = _blocking_rule("AC-TEST-WRONG")
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    assert staged.state == StageRecordState.QUALITY_FAILED
    assert staged.dqa_summary["blocking_failures"]

    # The rule was wrong; it is retired and the record re-checked.
    rule.status = RuleStatus.RETIRED
    rule.save(update_fields=["status"])
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()

    assert staged.state != StageRecordState.QUALITY_FAILED
    assert staged.dqa_summary["blocking_failures"] == [], (
        "the finding must be replaced by a real re-evaluation"
    )


def test_a_record_can_be_re_checked_from_pending_promotion(staged):
    """A record that already passed is not frozen: a new rule can put it
    back into the queue."""
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    assert staged.state == StageRecordState.PENDING_PROMOTION

    _blocking_rule("AC-TEST-NEW-RULE")
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    assert staged.state == StageRecordState.QUALITY_FAILED


def test_re_checking_a_clean_record_leaves_it_where_it_was(staged):
    """Re-running is safe to repeat — the operator pressing it twice
    must not move a record somewhere new."""
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    first = staged.state
    for _ in range(3):
        process_stage_record(staged, actor="op-1")
        staged.refresh_from_db()
    assert staged.state == first


def test_re_checking_does_not_accumulate_duplicate_findings(staged):
    """Each run replaces the summary rather than appending to it.

    The count is per failing member, not per rule — this household has
    two, so one member-scope rule yields two findings on every run. What
    must not happen is that number growing each time the operator
    presses the button.
    """
    _blocking_rule("AC-TEST-REPEAT")
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    after_one = len(staged.dqa_summary["blocking_failures"])
    assert after_one == 2, "one finding per member of this two-member household"

    for _ in range(3):
        process_stage_record(staged, actor="op-1")
        staged.refresh_from_db()
    assert len(staged.dqa_summary["blocking_failures"]) == after_one


def test_a_promoted_record_is_not_re_processed(staged):
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    promote_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    assert staged.state == StageRecordState.PROMOTED

    process_stage_record(staged, actor="op-1")   # no-op, not an error
    staged.refresh_from_db()
    assert staged.state == StageRecordState.PROMOTED


def test_an_archived_record_stays_archived(staged):
    """Archiving is one-way. A re-run must not resurrect a record an
    operator deliberately took out of the queue."""
    _blocking_rule("AC-TEST-ARCHIVE")
    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    quarantine_stage_record(staged, actor="op-1", reason="test fixture")
    staged.refresh_from_db()

    process_stage_record(staged, actor="op-1")
    staged.refresh_from_db()
    assert staged.state == StageRecordState.QUARANTINED


# --- the path the console's button actually takes --------------------------

def _admin(django_user_model):
    from django.contrib.auth.models import Group
    user = django_user_model.objects.create_user(username="queue-op", password="x")
    group, _ = Group.objects.get_or_create(name="nsr_admin")
    user.groups.add(group)
    return user


def test_the_endpoint_re_runs_the_gates(staged, django_user_model):
    client = APIClient()
    client.force_authenticate(_admin(django_user_model))
    response = client.post(
        f"/api/v1/dih/stage-records/{staged.id}/process/",
        {"allow_fast_track": True}, format="json",
    )
    assert response.status_code == 200, response.content
    staged.refresh_from_db()
    assert staged.state == StageRecordState.PENDING_PROMOTION


def test_the_endpoint_can_be_called_again_on_the_same_record(staged, django_user_model):
    """What "check it again in the queue" means in practice."""
    client = APIClient()
    client.force_authenticate(_admin(django_user_model))
    url = f"/api/v1/dih/stage-records/{staged.id}/process/"
    assert client.post(url, {"allow_fast_track": True}, format="json").status_code == 200
    assert client.post(url, {"allow_fast_track": True}, format="json").status_code == 200


def test_the_audit_names_the_signed_in_operator_not_the_body(staged, django_user_model):
    """The console posts a hardcoded `actor: "nsr-reviewer"`. The view
    takes the actor from the session, so the chain records who actually
    pressed it."""
    client = APIClient()
    client.force_authenticate(_admin(django_user_model))
    client.post(
        f"/api/v1/dih/stage-records/{staged.id}/process/",
        {"allow_fast_track": True, "actor": "somebody-else"}, format="json",
    )
    actors = set(
        AuditEvent.objects.filter(entity_id=staged.id).values_list("actor_id", flat=True),
    )
    assert "somebody-else" not in actors
    assert "queue-op" in actors


def test_an_anonymous_caller_cannot_re_run_the_gates(staged):
    response = APIClient().post(
        f"/api/v1/dih/stage-records/{staged.id}/process/",
        {"allow_fast_track": True}, format="json",
    )
    assert response.status_code in (401, 403), response.status_code
