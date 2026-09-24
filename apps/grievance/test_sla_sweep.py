"""The SLA sweep: escalate what has breached, once, and stop at L4.

Nothing escalated a breached case. Production held cases 2,900 hours
past their deadline with nobody above them told, because escalation was
only ever a manual act.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.grievance.models import Category, Grievance, GrievanceStatus, Tier
from apps.grievance.services import open_grievance
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db


def _run(*args):
    out = StringIO()
    call_command("escalate_breached_grievances", *args, stdout=out)
    return out.getvalue()


def _breached(tier=Tier.L1_PARISH_CHIEF, status=GrievanceStatus.OPEN):
    g = open_grievance(
        category=Category.OTHER, description="[TEST] breached", tier=tier,
    )
    Grievance.objects.filter(pk=g.pk).update(
        status=status, sla_deadline=timezone.now() - timedelta(hours=5),
    )
    g.refresh_from_db()
    return g


def test_dry_run_changes_nothing():
    g = _breached()

    output = _run()

    assert "Dry run" in output
    g.refresh_from_db()
    assert g.tier == Tier.L1_PARISH_CHIEF


@pytest.mark.parametrize(
    "status",
    [GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS,
     GrievanceStatus.ESCALATED],
)
def test_a_breached_live_case_escalates(status):
    g = _breached(status=status)

    _run("--apply")

    g.refresh_from_db()
    assert g.tier == Tier.L2_CDO
    assert g.status == GrievanceStatus.ESCALATED


def test_it_moves_exactly_one_tier():
    """A case does not jump L1 to L4 and skip the people in between."""
    g = _breached()

    _run("--apply")

    g.refresh_from_db()
    assert g.tier == Tier.L2_CDO


def test_it_is_idempotent():
    """Escalation restarts the tier clock, so the second run finds
    nothing — the case is not breached at its NEW tier."""
    g = _breached()

    _run("--apply")
    g.refresh_from_db()
    tier_after_first = g.tier
    _run("--apply")

    g.refresh_from_db()
    assert g.tier == tier_after_first == Tier.L2_CDO


def test_an_l4_case_is_flagged_not_escalated():
    g = _breached(tier=Tier.L4_NSR_UNIT)

    _run("--apply")

    g.refresh_from_db()
    assert g.tier == Tier.L4_NSR_UNIT
    assert g.sla_breach_flagged_at is not None


def test_an_l4_case_is_flagged_only_once():
    g = _breached(tier=Tier.L4_NSR_UNIT)

    _run("--apply")
    g.refresh_from_db()
    first = g.sla_breach_flagged_at
    _run("--apply")

    g.refresh_from_db()
    assert g.sla_breach_flagged_at == first


def test_a_case_inside_its_window_is_untouched():
    g = open_grievance(category=Category.OTHER, description="[TEST] fresh")

    _run("--apply")

    g.refresh_from_db()
    assert g.tier == Tier.L1_PARISH_CHIEF


@pytest.mark.parametrize(
    "status", [GrievanceStatus.RESOLVED, GrievanceStatus.CLOSED],
)
def test_a_finished_case_is_never_escalated(status):
    """Nothing is owed on a case that is done, however old it is."""
    g = _breached(status=status)

    _run("--apply")

    g.refresh_from_db()
    assert g.tier == Tier.L1_PARISH_CHIEF


def test_the_escalation_is_attributed_to_the_system():
    g = _breached()

    _run("--apply")

    event = AuditEvent.objects.filter(
        entity_type="grievance", entity_id=g.id, actor_id="system",
    ).order_by("-occurred_at").first()
    assert event is not None
    assert "SLA breached" in event.reason


def test_the_l4_flag_is_audited_too():
    g = _breached(tier=Tier.L4_NSR_UNIT)

    _run("--apply")

    event = AuditEvent.objects.filter(
        entity_type="grievance", entity_id=g.id, actor_id="system",
    ).first()
    assert event is not None
    assert "no tier above" in event.reason
