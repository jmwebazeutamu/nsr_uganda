"""Consent propagation integration tests (US-CONSENT-12,13,15,16).

Exercises the downstream gates wired into PMT, REF, DDUP, and UPD. Each gate
is inert when CONSENT_MODULE_ENABLED is off or when consent is un-captured;
the tests force the flag ON and capture explicit states.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.utils import timezone

from apps.security.models import AuditEvent

from . import services
from .models import ConsentPurpose, ConsentRecord, ConsentState


@pytest.fixture(autouse=True)
def _flag_on(settings):
    settings.CONSENT_MODULE_ENABLED = True


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


def _household_with_head(geo, *, surname="Okot"):
    from apps.data_management.models import Household, Member
    hh = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"],
        county=geo["c"], sub_county=geo["sc"], parish=geo["p"],
        village=geo["v"], urban_rural="2", address_narrative="Plot 7",
    )
    head = Member.objects.create(
        household=hh, line_number=1, surname=surname, first_name="James",
        sex="1", age_years=40, relationship_to_head="01",
    )
    hh.head_member = head
    hh.save(update_fields=["head_member"])
    return hh, head


def _purpose(code):
    return ConsentPurpose.objects.get(code=code)


def _last(action):
    return AuditEvent.objects.filter(action=action).order_by("-occurred_at").first()


# ---------------------------------------------------------------------------
# US-CONSENT-12 — PMT ELIGIBILITY gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pmt_recompute_blocked_when_eligibility_withdrawn(geo):
    from apps.pmt.services import recompute_for_household
    hh, head = _household_with_head(geo)
    services.capture_consent(
        member=head, purpose=_purpose("ELIGIBILITY"),
        state=ConsentState.WITHDRAWN, captured_via="WEB_INTAKE", captured_by="op1")
    result = recompute_for_household(hh, actor="op1")
    assert result is None
    assert _last("pmt.recompute.blocked.consent_withdrawn") is not None


@pytest.mark.django_db
def test_pmt_recompute_blocked_when_pending_reconsent(geo):
    from apps.pmt.services import recompute_for_household
    hh, head = _household_with_head(geo)
    services.capture_consent(
        member=head, purpose=_purpose("ELIGIBILITY"),
        state=ConsentState.PENDING_RE_CONSENT, captured_via="WEB_INTAKE",
        captured_by="op1")
    assert recompute_for_household(hh, actor="op1") is None
    assert _last("pmt.recompute.blocked.pending_reconsent") is not None


# ---------------------------------------------------------------------------
# US-CONSENT-13 — REF referral gate
# ---------------------------------------------------------------------------


def _programme():
    from apps.partners.models import Partner, Programme
    opm = Partner.objects.create(
        code="OPM", name="Office of the Prime Minister",
        type="ministry", status="active")
    return Programme.objects.create(
        partner=opm, code="PDM", name="Parish Development Model",
        kind="cash_transfer", status="active",
        webhook_url="https://pdm.example/incoming",
        webhook_secret_encrypted=b"test-secret",
        dsa_reference_legacy="DSA-OPM-PDM-2026-001")


@pytest.mark.django_db
def test_send_referral_blocked_when_referral_withdrawn(geo):
    from apps.referral.services import ReferralError, send_referral
    hh, head = _household_with_head(geo)
    services.capture_consent(
        member=head, purpose=_purpose("REFERRAL"), state=ConsentState.WITHDRAWN,
        captured_via="WEB_INTAKE", captured_by="op1")
    with pytest.raises(ReferralError):
        send_referral(programme=_programme(), household=hh, actor="op1")


@pytest.mark.django_db
def test_send_referral_allowed_when_uncaptured(geo):
    """Un-captured REFERRAL consent must NOT block — gate stays inert until a
    citizen actively withdraws."""
    from apps.referral.services import send_referral
    hh, _head = _household_with_head(geo)
    referral = send_referral(programme=_programme(), household=hh, actor="op1")
    assert referral.status


# ---------------------------------------------------------------------------
# US-CONSENT-15 — DDUP merge reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_merge_reconciliation_conflict_raises(geo):
    hh, survivor = _household_with_head(geo)
    from apps.data_management.models import Member
    loser = Member.objects.create(
        household=hh, line_number=2, surname="Okot", first_name="Jim",
        sex="1", age_years=41)
    p = _purpose("PAYMENTS")
    services.capture_consent(member=survivor, purpose=p, state=ConsentState.GRANTED,
                             captured_via="WEB_INTAKE", captured_by="op1")
    services.capture_consent(member=loser, purpose=p, state=ConsentState.REFUSED,
                             captured_via="WEB_INTAKE", captured_by="op1")
    with pytest.raises(services.ConsentError):
        services.reconcile_consent_on_merge(surviving=survivor, loser=loser, actor="op1")


@pytest.mark.django_db
def test_merge_reconciliation_union_and_withdrawal(geo):
    hh, survivor = _household_with_head(geo)
    from apps.data_management.models import Member
    loser = Member.objects.create(
        household=hh, line_number=2, surname="Okot", first_name="Jim",
        sex="1", age_years=41)
    granted = _purpose("PAYMENTS")
    withdrawn = _purpose("REFERRAL")
    # Union: loser GRANTED, survivor none → survivor becomes GRANTED.
    services.capture_consent(member=loser, purpose=granted, state=ConsentState.GRANTED,
                             captured_via="WEB_INTAKE", captured_by="op1")
    # Withdrawal wins: survivor GRANTED, loser WITHDRAWN → survivor WITHDRAWN.
    services.capture_consent(member=survivor, purpose=withdrawn, state=ConsentState.GRANTED,
                             captured_via="WEB_INTAKE", captured_by="op1")
    services.capture_consent(member=loser, purpose=withdrawn, state=ConsentState.WITHDRAWN,
                             captured_via="WEB_INTAKE", captured_by="op1")

    out = services.reconcile_consent_on_merge(surviving=survivor, loser=loser, actor="op1")
    assert out["reconciled"] == 2
    sg = ConsentRecord.objects.get(member=survivor, purpose=granted)
    assert sg.state == ConsentState.GRANTED
    sw = ConsentRecord.objects.get(member=survivor, purpose=withdrawn)
    assert sw.state == ConsentState.WITHDRAWN


# ---------------------------------------------------------------------------
# US-CONSENT-16 — UPD head-change re-consent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_head_change_opens_recapture_when_no_registration_consent(geo):
    hh, head = _household_with_head(geo)
    opened = services.require_head_registration_consent(head_member=head, actor="chief1")
    assert opened is True
    rec = ConsentRecord.objects.get(member=head, purpose__code="REGISTRATION")
    assert rec.state == ConsentState.PENDING_RE_CONSENT
    assert rec.captured_via == "UPD_RECAPTURE"
    assert _last("consent.upd.recapture_required") is not None


@pytest.mark.django_db
def test_head_change_noop_when_already_granted(geo):
    hh, head = _household_with_head(geo)
    services.capture_consent(
        member=head, purpose=_purpose("REGISTRATION"), state=ConsentState.GRANTED,
        captured_via="WEB_INTAKE", captured_by="op1")
    assert services.require_head_registration_consent(head_member=head, actor="chief1") is False


# ---------------------------------------------------------------------------
# US-CONSENT-11 — DIH fast-track synthetic consent
# ---------------------------------------------------------------------------


def _source_system_with_dpa(*, ratified=True, consent_purposes=("REGISTRATION", "ELIGIBILITY")):
    from apps.ingestion_hub.models import DataProvisionAgreement, SourceSystem
    src = SourceSystem.objects.create(code="UBOS", name="UBOS", kind="ubos")
    DataProvisionAgreement.objects.create(
        source_system=src, reference="DPA-UBOS-2026-001",
        scope={"consent_purposes": list(consent_purposes),
               "dpa_document_key": "minio://dpa/ubos-2026.pdf"},
        valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1),
        signed_at=timezone.now() if ratified else None,
        approved_by="dpo1" if ratified else "")
    return src


@pytest.mark.django_db
def test_fast_track_writes_synthetic_consent_when_ratified(geo):
    hh, head = _household_with_head(geo)
    src = _source_system_with_dpa()
    out = services.fast_track_dpa_consent(household=hh, source_system=src, actor="dih")
    assert out["written"] == 2
    rec = ConsentRecord.objects.get(member=head, purpose__code="REGISTRATION")
    assert rec.state == ConsentState.GRANTED
    assert rec.captured_via == "DIH_FAST_TRACK" and rec.capture_method == "DIGITAL"
    assert rec.evidence.filter(evidence_type="DPA_DOCUMENT").exists()


@pytest.mark.django_db
def test_fast_track_held_when_dpa_not_ratified(geo):
    hh, _head = _household_with_head(geo)
    src = _source_system_with_dpa(ratified=False)
    with pytest.raises(services.ConsentError) as exc:
        services.fast_track_dpa_consent(household=hh, source_system=src, actor="dih")
    assert services.PROMOTION_BLOCKED_DPA_NOT_RATIFIED in str(exc.value)


@pytest.mark.django_db
def test_intake_consent_refused_helper():
    assert services.intake_consent_refused({"consent": "2"}) is True
    assert services.intake_consent_refused({"consent": "no"}) is True
    assert services.intake_consent_refused({"consent": "1"}) is False
    assert services.intake_consent_refused({}) is False  # missing = not a refusal


@pytest.mark.django_db
def test_capture_intake_consent_block_per_purpose(geo):
    hh, head = _household_with_head(geo)
    payload = {"consent": "1", "consent_block": {
        "REGISTRATION": "GRANTED", "REFERRAL": "GRANTED", "PAYMENTS": "REFUSED",
        "_method": "VERBAL_WITNESSED", "_witness_name": "Mukasa", "_witness_role": "LC1",
    }}
    out = services.capture_intake_consent(household=hh, payload=payload, actor="op1")
    assert out["captured"] == 3
    recs = {r.purpose.code: r for r in ConsentRecord.objects.filter(member=head)}
    assert recs["REGISTRATION"].state == ConsentState.GRANTED
    assert recs["PAYMENTS"].state == ConsentState.REFUSED
    assert recs["REGISTRATION"].capture_method == "VERBAL_WITNESSED"
    # Witness evidence recorded for the verbal grant.
    assert recs["REGISTRATION"].evidence.filter(evidence_type="WITNESS_STATEMENT").exists()


@pytest.mark.django_db
def test_capture_intake_consent_single_refused(geo):
    hh, head = _household_with_head(geo)
    out = services.capture_intake_consent(household=hh, payload={"consent": "2"}, actor="op1")
    assert out["captured"] == 1
    assert ConsentRecord.objects.get(
        member=head, purpose__code="REGISTRATION").state == ConsentState.REFUSED


@pytest.mark.django_db
def test_fast_track_noop_when_no_consent_purposes(geo):
    hh, _head = _household_with_head(geo)
    src = _source_system_with_dpa(consent_purposes=())
    out = services.fast_track_dpa_consent(household=hh, source_system=src, actor="dih")
    assert out["written"] == 0


# ---------------------------------------------------------------------------
# US-CONSENT-14 — DRS row-level consent gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_drs_bundle_excludes_members_without_research_consent(geo):
    from apps.data_management.models import Member
    from apps.data_requests.bundles import render_bundle
    from apps.data_requests.models import DataRequest
    from apps.data_requests.test_helpers import make_dsa, make_partner

    hh, head = _household_with_head(geo)  # member 1 (head)
    member2 = Member.objects.create(
        household=hh, line_number=2, surname="Okot", first_name="Mary",
        sex="2", age_years=30)

    # member2 withdrew RESEARCH consent; head did not.
    services.capture_consent(
        member=member2, purpose=_purpose("RESEARCH"), state=ConsentState.WITHDRAWN,
        captured_via="WEB_INTAKE", captured_by="op1")

    partner = make_partner(code="RES-OPM", name="Research OPM")
    dsa = make_dsa(
        partner=partner, reference="DSA-RES-001", status="active",
        allowed_scopes={"fields": ["household.id", "member.surname"]})
    # Map this DSA's scope to the RESEARCH consent purpose.
    dsa.entities_scope = {**(dsa.entities_scope or {}), "consent_purposes": ["RESEARCH"]}
    dsa.save(update_fields=["entities_scope"])

    req = DataRequest.objects.create(
        dsa=dsa, requester="partner-x",
        request_payload={"fields": ["household.id", "member.surname"]})

    body, count = render_bundle(req)
    assert count == 1
    text = body.decode("utf-8")
    # The head (member 1) is included; member 2 (withdrew RESEARCH) is excluded.
    assert head.surname in text
    member_lines = [m for m in text.split("members") if "Mary" in m]
    assert not member_lines, "member who withdrew RESEARCH consent leaked into the extract"


@pytest.mark.django_db
def test_drs_bundle_ungated_when_dsa_declares_no_consent_purposes(geo):
    from apps.data_management.models import Member
    from apps.data_requests.bundles import render_bundle
    from apps.data_requests.models import DataRequest
    from apps.data_requests.test_helpers import make_dsa, make_partner

    hh, _head = _household_with_head(geo)
    member2 = Member.objects.create(
        household=hh, line_number=2, surname="Okot", first_name="Mary",
        sex="2", age_years=30)
    services.capture_consent(
        member=member2, purpose=_purpose("RESEARCH"), state=ConsentState.WITHDRAWN,
        captured_via="WEB_INTAKE", captured_by="op1")

    partner = make_partner(code="RES-OPM2", name="Research OPM2")
    dsa = make_dsa(
        partner=partner, reference="DSA-RES-002", status="active",
        allowed_scopes={"fields": ["household.id", "member.surname"]})
    req = DataRequest.objects.create(
        dsa=dsa, requester="partner-x",
        request_payload={"fields": ["household.id", "member.surname"]})

    body, _count = render_bundle(req)
    # No consent_purposes on the DSA → no per-member gating; Mary stays in.
    assert "Mary" in body.decode("utf-8")
