"""Tests for the AC-CONSENT-* DQA rule seed (US-CONSENT-09) and the
withdrawal SLA sweep task (US-CONSENT-07)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.security.models import AuditEvent

from .models import ConsentPurpose, ConsentWithdrawalTicket, TicketState


@pytest.fixture(autouse=True)
def _flag_on(settings):
    settings.CONSENT_MODULE_ENABLED = True


# ---------------------------------------------------------------------------
# US-CONSENT-09 — rule seed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seed_creates_five_draft_rules():
    from scripts.seed_dqa_consent_rules import RULES, seed

    from apps.dqa.models import RuleStatus

    rows = seed()
    assert len(rows) == len(RULES) == 5
    codes = {r.rule_id for r in rows}
    assert "AC-CONSENT-MANDATORY" in codes
    assert "AC-CONSENT-MINOR-PROXY-PRESENT" in codes
    # Seeded DRAFT — DPO ratifies before activation.
    assert all(r.status == RuleStatus.DRAFT for r in rows)


@pytest.mark.django_db
def test_seed_activate_walks_dual_approval():
    from scripts.seed_dqa_consent_rules import seed

    from apps.dqa.models import RuleStatus

    rows = seed(activate=True)
    assert all(r.status == RuleStatus.ACTIVE for r in rows)
    # author != approver was enforced (no exception raised) and each rule has
    # a distinct approver.
    assert all(r.approved_by and r.approved_by != r.author for r in rows)


@pytest.mark.django_db
def test_seed_is_idempotent():
    from scripts.seed_dqa_consent_rules import seed

    from apps.dqa.models import DqaRule

    seed()
    seed()
    assert DqaRule.objects.filter(rule_id__startswith="AC-CONSENT-").count() == 5


# ---------------------------------------------------------------------------
# US-CONSENT-07 — SLA sweep
# ---------------------------------------------------------------------------


def _make_member():
    from apps.data_management.models import Household, Member
    from apps.reference_data.models import GeographicUnit
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"S-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1))
    hh = Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
        village=nodes["v"], urban_rural="2", address_narrative="X")
    return Member.objects.create(
        household=hh, line_number=1, surname="A", first_name="B", sex="1")


@pytest.mark.django_db
def test_sla_sweep_alerts_breached_ticket_once():
    from .tasks import scan_withdrawal_sla_breaches

    member = _make_member()
    purpose = ConsentPurpose.objects.get(code="REGISTRATION")
    now = timezone.now()
    ticket = ConsentWithdrawalTicket.objects.create(
        member=member, purpose=purpose, state=TicketState.OPEN,
        requested_by="cit", requested_at_day=now.date(),
        sla_deadline=now - timedelta(days=1))  # already breached

    out = scan_withdrawal_sla_breaches()
    assert out["breached"] == 1
    ev = AuditEvent.objects.filter(action="consent.withdrawal.sla_breached").first()
    assert ev is not None and ev.entity_id == ticket.id
    ticket.refresh_from_db()
    assert ticket.sla_breached_notified_at is not None

    # Second sweep does not re-alert.
    assert scan_withdrawal_sla_breaches()["breached"] == 0


@pytest.mark.django_db
def test_sla_sweep_ignores_in_window_ticket():
    from .tasks import scan_withdrawal_sla_breaches

    member = _make_member()
    purpose = ConsentPurpose.objects.get(code="REGISTRATION")
    now = timezone.now()
    ConsentWithdrawalTicket.objects.create(
        member=member, purpose=purpose, state=TicketState.OPEN,
        requested_by="cit", requested_at_day=now.date(),
        sla_deadline=now + timedelta(days=20))
    assert scan_withdrawal_sla_breaches()["breached"] == 0
