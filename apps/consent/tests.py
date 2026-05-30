"""Consent Management — unit + contract tests (US-CONSENT-01,02,06,07,09,10).

Test-first per CLAUDE.md (consent is audit-bearing). Fixtures use SENTINEL
purpose codes / version 900+ where they would otherwise collide with the
migration-seeded production catalogue (project memory: seeded-row fixture
pattern). The module flag is forced ON via the `settings` fixture so the suite
is deterministic regardless of the env's DEBUG value.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.security.models import AuditEvent

from . import services
from .models import (
    CaptureMethod,
    ConsentPurpose,
    ConsentRecordVersion,
    ConsentState,
    ConsentStatementVersion,
    ConsentWithdrawalTicket,
    LifecycleStatus,
    StatementStatus,
    TicketState,
    WithdrawalDecisionType,
)


@pytest.fixture(autouse=True)
def _flag_on(settings):
    settings.CONSENT_MODULE_ENABLED = True
    settings.CONSENT_WITHDRAWAL_SLA_DAYS = 30


@pytest.fixture
def geo(db):
    from apps.reference_data.models import GeographicUnit
    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"),
        ("district", "d", "sr"), ("county", "c", "d"),
        ("sub_county", "sc", "c"), ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"U-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return nodes


def _make_member(geo, *, line=1, age=40, surname="Okot"):
    from apps.data_management.models import Household, Member
    hh = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"], urban_rural="2", address_narrative="Plot 7",
    )
    return Member.objects.create(
        household=hh, line_number=line, surname=surname,
        first_name="James", sex="1", age_years=age,
    )


@pytest.fixture
def member(geo):
    return _make_member(geo)


def _draft_purpose(code="SENTINEL_PURPOSE", *, withdrawable=True, author="alice"):
    return ConsentPurpose.objects.create(
        code=code, name="Sentinel", lawful_basis="CONSENT",
        withdrawable=withdrawable, author=author,
        status=LifecycleStatus.DRAFT,
    )


def _last_audit(action):
    return (AuditEvent.objects.filter(action=action)
            .order_by("-occurred_at").first())


# ---------------------------------------------------------------------------
# Seed integrity (CONSENT-O-01)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_purpose_catalogue_seeded_scope_doc_nine():
    codes = set(ConsentPurpose.objects.values_list("code", flat=True))
    expected = {
        "REGISTRATION", "ELIGIBILITY", "REFERRAL", "PAYMENTS",
        "COMMUNICATIONS_SMS", "COMMUNICATIONS_USSD", "RESEARCH",
        "STATISTICS", "GRIEVANCE_CONTACT",
    }
    assert expected <= codes
    # The designer's inferred purpose must NOT be seeded (decision 2026-05-30).
    assert "IDENTITY_VERIFICATION" not in codes
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    assert reg.status == LifecycleStatus.ACTIVE and reg.is_primary
    stats = ConsentPurpose.objects.get(code="STATISTICS")
    assert stats.withdrawable is False


@pytest.mark.django_db
def test_registration_statement_v3_seeded():
    stmt = ConsentStatementVersion.objects.get(
        purpose__code="REGISTRATION", version=3)
    assert stmt.status == StatementStatus.ACTIVE
    assert "en" in stmt.text_i18n
    assert len(stmt.placeholder_languages) == 6


# ---------------------------------------------------------------------------
# consent_state() gate (US-CONSENT-10 / integration contract)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_consent_state_transparent_allow_when_flag_off(settings, member):
    settings.CONSENT_MODULE_ENABLED = False
    assert services.consent_state(member.id, "REGISTRATION") == services.TRANSPARENT_ALLOW
    assert services.is_granted(member.id, "REGISTRATION") is True


@pytest.mark.django_db
def test_consent_state_pending_when_no_record(member):
    assert services.consent_state(member.id, "REGISTRATION") == ConsentState.PENDING_REVIEW
    assert services.is_granted(member.id, "REGISTRATION") is False


# ---------------------------------------------------------------------------
# US-CONSENT-01 — purpose dual-approval
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_activate_purpose_rejects_self_approval():
    p = _draft_purpose(author="alice")
    services.submit_purpose_for_approval(p, actor="alice")
    with pytest.raises(services.ApprovalError):
        services.activate_purpose(p, approver="alice", note="ok")


@pytest.mark.django_db
def test_activate_purpose_requires_note():
    p = _draft_purpose(author="alice")
    services.submit_purpose_for_approval(p, actor="alice")
    with pytest.raises(services.ApprovalError):
        services.activate_purpose(p, approver="bob", note="  ")


@pytest.mark.django_db
def test_activate_purpose_success_emits_audit():
    p = _draft_purpose(author="alice")
    services.submit_purpose_for_approval(p, actor="alice")
    services.activate_purpose(p, approver="bob", note="reviewed")
    p.refresh_from_db()
    assert p.status == LifecycleStatus.ACTIVE and p.approved_by == "bob"
    ev = _last_audit("consent.purpose.activated")
    assert ev is not None
    assert ev.entity_type == "consent.purpose"
    assert ev.entity_id == p.id
    assert ev.field_changes["purpose_code"] == "SENTINEL_PURPOSE"


# ---------------------------------------------------------------------------
# US-CONSENT-02 — statement supersession + material re-consent (CR2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_material_statement_activation_flags_reconsent(member):
    p = _draft_purpose()
    services.submit_purpose_for_approval(p, actor="alice")
    services.activate_purpose(p, approver="bob", note="ok")

    # An existing GRANTED record on the purpose.
    rec = services.capture_consent(
        member=member, purpose=p, state=ConsentState.GRANTED,
        captured_via="WEB_INTAKE", captured_by="op1")

    v1 = ConsentStatementVersion.objects.create(
        purpose=p, version=900, status=StatementStatus.PENDING_APPROVAL,
        author="alice", text_i18n={"en": "v900"})
    services.activate_statement(v1, approver="bob", note="first")

    v2 = ConsentStatementVersion.objects.create(
        purpose=p, version=901, status=StatementStatus.PENDING_APPROVAL,
        author="alice", is_material=True, text_i18n={"en": "v901"})
    assert services.pending_reconsent_count(p) == 1
    services.activate_statement(v2, approver="bob", note="material change")

    v1.refresh_from_db()
    assert v1.status == StatementStatus.SUPERSEDED
    rec.refresh_from_db()
    assert rec.state == ConsentState.PENDING_RE_CONSENT
    assert _last_audit("consent.statement.activated") is not None
    assert _last_audit("consent.statement.superseded") is not None


@pytest.mark.django_db
def test_one_active_statement_per_purpose_enforced(member):
    """Two ACTIVE statements on one purpose must not coexist (supersession
    handles it; a direct second activate supersedes the first)."""
    p = _draft_purpose()
    services.submit_purpose_for_approval(p, actor="alice")
    services.activate_purpose(p, approver="bob", note="ok")
    a = ConsentStatementVersion.objects.create(
        purpose=p, version=900, status=StatementStatus.PENDING_APPROVAL,
        author="alice", text_i18n={"en": "a"})
    services.activate_statement(a, approver="bob", note="a")
    b = ConsentStatementVersion.objects.create(
        purpose=p, version=901, status=StatementStatus.PENDING_APPROVAL,
        author="alice", text_i18n={"en": "b"})
    services.activate_statement(b, approver="bob", note="b")
    active = ConsentStatementVersion.objects.filter(
        purpose=p, status=StatementStatus.ACTIVE)
    assert active.count() == 1 and active.first().version == 901


# ---------------------------------------------------------------------------
# US-CONSENT-10 — capture writes audit + version with the audit link
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_capture_granted_emits_audit_and_version(member):
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    rec = services.capture_consent(
        member=member, purpose=reg, state=ConsentState.GRANTED,
        captured_via="WEB_INTAKE", capture_method=CaptureMethod.SIGNATURE,
        captured_by="op1")
    assert rec.state == ConsentState.GRANTED
    assert rec.sub_region_code == "U-SR"  # inherited from member.household
    ev = _last_audit("consent.granted")
    assert ev is not None and ev.entity_id == rec.id
    version = ConsentRecordVersion.objects.get(consent_record=rec)
    assert version.state == ConsentState.GRANTED
    # The integrity link: every version row names the AuditEvent of its change.
    assert version.audit_event_id == ev.id


@pytest.mark.django_db
def test_capture_refused_emits_refused(member):
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    services.capture_consent(
        member=member, purpose=reg, state=ConsentState.REFUSED,
        captured_via="WEB_INTAKE", captured_by="op1")
    assert _last_audit("consent.refused") is not None


# ---------------------------------------------------------------------------
# US-CONSENT-06 / -07 — withdrawal idempotency + DPO decision
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_withdrawal_idempotent_per_day(member):
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    services.capture_consent(
        member=member, purpose=reg, state=ConsentState.GRANTED,
        captured_via="WEB_INTAKE", captured_by="op1")
    t1 = services.open_withdrawal_ticket(member=member, purpose=reg, requested_by="cit")
    t2 = services.open_withdrawal_ticket(member=member, purpose=reg, requested_by="cit")
    assert t1.id == t2.id
    assert ConsentWithdrawalTicket.objects.filter(member=member, purpose=reg).count() == 1
    assert AuditEvent.objects.filter(action="consent.withdrawal.ticket_opened").count() == 1


@pytest.mark.django_db
def test_withdraw_non_withdrawable_purpose_raises(member):
    stats = ConsentPurpose.objects.get(code="STATISTICS")
    with pytest.raises(services.ConsentError):
        services.open_withdrawal_ticket(member=member, purpose=stats, requested_by="cit")


@pytest.mark.django_db
def test_decide_confirm_withdraws_record(member):
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    rec = services.capture_consent(
        member=member, purpose=reg, state=ConsentState.GRANTED,
        captured_via="WEB_INTAKE", captured_by="op1")
    ticket = services.open_withdrawal_ticket(member=member, purpose=reg, requested_by="cit")
    services.decide_withdrawal(
        ticket, decision=WithdrawalDecisionType.CONFIRM,
        rationale="valid request", decided_by="dpo1")
    ticket.refresh_from_db()
    rec.refresh_from_db()
    assert ticket.state == TicketState.CONFIRMED and ticket.closed_at is not None
    assert rec.state == ConsentState.WITHDRAWN
    assert _last_audit("consent.withdrawn") is not None
    assert _last_audit("consent.withdrawal.ticket_decided") is not None


@pytest.mark.django_db
def test_decide_requires_rationale(member):
    reg = ConsentPurpose.objects.get(code="REGISTRATION")
    ticket = services.open_withdrawal_ticket(member=member, purpose=reg, requested_by="cit")
    with pytest.raises(services.ConsentError):
        services.decide_withdrawal(
            ticket, decision=WithdrawalDecisionType.CONFIRM,
            rationale="  ", decided_by="dpo1")


# ---------------------------------------------------------------------------
# US-CONSENT-09 — capture-time DQA hooks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verbal_consent_requires_witness(member):
    from .dqa_hooks import check_capture
    errs = check_capture(
        state=ConsentState.GRANTED, capture_method=CaptureMethod.VERBAL_WITNESSED,
        witness_name="", witness_role="", member=member,
        proxy_relationship="", purpose_code="REGISTRATION")
    assert any(e["code"] == "AC-CONSENT-METHOD-VALID" for e in errs)


@pytest.mark.django_db
def test_minor_requires_proxy(geo):
    from .dqa_hooks import check_capture
    minor = _make_member(geo, line=2, age=10, surname="Child")
    errs = check_capture(
        state=ConsentState.GRANTED, capture_method=CaptureMethod.SIGNATURE,
        witness_name="", witness_role="", member=minor,
        proxy_relationship="", purpose_code="REGISTRATION")
    assert any(e["code"] == "AC-CONSENT-MINOR-PROXY-PRESENT" for e in errs)


# ---------------------------------------------------------------------------
# API flag gate + happy path
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(db):
    from rest_framework.test import APIClient
    user = get_user_model().objects.create_user(username="op1", password="x")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_api_returns_503_when_flag_off(settings, api_client):
    settings.CONSENT_MODULE_ENABLED = False
    resp = api_client.get("/api/v1/consent/purposes/")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_api_member_capture_and_matrix(api_client, member):
    resp = api_client.post(
        f"/api/v1/consent/members/{member.id}/capture",
        {"purpose_code": "REGISTRATION", "state": "GRANTED",
         "capture_method": "SIGNATURE"}, format="json")
    assert resp.status_code == 201, resp.content
    matrix = api_client.get(f"/api/v1/consent/members/{member.id}")
    assert matrix.status_code == 200
    reg = [p for p in matrix.json()["purposes"] if p["purpose_code"] == "REGISTRATION"][0]
    assert reg["state"] == "GRANTED"


@pytest.mark.django_db
def test_api_capture_verbal_without_witness_rejected(api_client, member):
    resp = api_client.post(
        f"/api/v1/consent/members/{member.id}/capture",
        {"purpose_code": "REGISTRATION", "state": "GRANTED",
         "capture_method": "VERBAL_WITNESSED"}, format="json")
    assert resp.status_code == 400
    assert any(e["code"] == "AC-CONSENT-METHOD-VALID"
               for e in resp.json()["errors"])


@pytest.mark.django_db
def test_api_coverage_dashboard(api_client, member):
    services.capture_consent(
        member=member, purpose=ConsentPurpose.objects.get(code="REGISTRATION"),
        state=ConsentState.GRANTED, captured_via="WEB_INTAKE", captured_by="op1")
    resp = api_client.get("/api/v1/consent/coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_purposes"] >= 9
    assert body["consent_records_by_state"].get("GRANTED") == 1
    assert "open_withdrawal_tickets" in body and "sla_breached" in body
