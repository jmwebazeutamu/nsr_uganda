"""DSA renewal + supersession tests — US-S27-005 / ADR-0016.

Covers `scope_service.renew`, the `/renew/` DRF action, and the
supersession step `_supersede_prior_active` that fires when a
v(N+1) reaches `status="active"` through the existing ADR-0012
sign-off chain.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
    Programme,
)
from apps.partners.services import scope as scope_service
from apps.partners.services import signature as signature_service
from apps.reference_data.services import clear_resolver_cache
from apps.security.models import AuditEvent

URL_DSAS = "/api/v1/dsas/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(settings, db):
    settings.PARTNERS_MODULE_ENABLED = True
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(username="renewer", password="p")
    c = APIClient()
    c.force_authenticate(user=u)
    return c, u


@pytest.fixture
def partner(db):
    return Partner.objects.create(
        code="OPM", name="OPM", type="ministry",
        sector="social_protection", status="active", tone="system",
    )


@pytest.fixture
def programme(db, partner):
    return Programme.objects.create(
        partner=partner, code="PDM", name="PDM",
        kind="cash_transfer", status="active",
    )


def _make_dsa(
    partner, *, status="active", version=1,
    reference="DSA-OPM-2026-001",
    monthly_row_budget=100_000,
):
    return DataSharingAgreement.objects.create(
        reference=reference, partner=partner, version=version,
        status=status,
        field_scope={"Identifiers": True, "PMT": True},
        entities_scope={"household": True, "member": False},
        monthly_row_budget=monthly_row_budget,
        sensitive_data_handling="none", retention_days=180,
        classification="restricted", breach_sla_hours=72,
    )


def _sign_all(dsa, *, actor="signer"):
    """Take a draft through submit + sign all three signatures so
    the DSA ends up active. Mirrors the production flow exactly —
    record_signature is what triggers supersession."""
    signature_service.submit_for_signoff(
        dsa, actor=actor,
        partner_signer_email="ps@x.go.ug",
        nsr_unit_lead_email="lead@x.go.ug",
        dpo_email="dpo@x.go.ug",
    )
    sigs = list(dsa.signatures.order_by("sequence_order"))
    for sig in sigs:
        signature_service.record_signature(sig, actor=actor)
    dsa.refresh_from_db()
    return dsa


# ---------------------------------------------------------------------------
# scope_service.renew — service-level
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRenewActive:
    def test_returns_v2_draft(self, partner):
        v1 = _make_dsa(partner, status="active")
        v2 = scope_service.renew(v1, actor="op-1")
        assert v2.id != v1.id
        assert v2.version == 2
        assert v2.status == "draft"
        assert v2.reference == v1.reference
        assert v2.partner_id == v1.partner_id

    def test_scope_copied_verbatim(self, partner):
        v1 = _make_dsa(
            partner, status="active", monthly_row_budget=250_000,
        )
        v2 = scope_service.renew(v1, actor="op-1")
        assert v2.monthly_row_budget == 250_000
        assert v2.field_scope == {"Identifiers": True, "PMT": True}
        assert v2.entities_scope == {"household": True, "member": False}

    def test_effective_dates_null(self, partner):
        from datetime import date
        v1 = _make_dsa(partner, status="active")
        v1.effective_from = date(2026, 1, 1)
        v1.effective_to = date(2026, 12, 31)
        v1.save(update_fields=["effective_from", "effective_to"])

        v2 = scope_service.renew(v1, actor="op-1")
        assert v2.effective_from is None
        assert v2.effective_to is None

    def test_v1_untouched(self, partner):
        v1 = _make_dsa(partner, status="active", monthly_row_budget=100_000)
        scope_service.renew(v1, actor="op-1")
        v1.refresh_from_db()
        assert v1.status == "active"
        assert v1.version == 1
        assert v1.monthly_row_budget == 100_000

    def test_emits_dsa_renewed_audit(self, partner):
        v1 = _make_dsa(partner, status="active")
        v2 = scope_service.renew(v1, actor="op-1")
        ev = AuditEvent.objects.get(
            entity_type="dsa", action="dsa_renewed",
            entity_id=str(v2.id),
        )
        assert ev.field_changes["source_dsa_id"] == str(v1.id)
        assert ev.field_changes["source_version"] == 1
        assert ev.field_changes["new_version"] == 2


@pytest.mark.django_db
class TestRenewRedirect:
    def test_renewed_redirects_to_latest_active(self, partner):
        v1 = _make_dsa(partner, status="renewed", version=1)
        v2 = _make_dsa(
            partner, status="active", version=2,
            reference="DSA-OPM-2026-001",
        )
        result = scope_service.renew(v1, actor="op-1")
        assert result.id == v2.id

    def test_renewed_with_no_active_raises(self, partner):
        # Edge case: everything has been renewed/expired/suspended.
        _make_dsa(
            partner, status="renewed", version=1,
            reference="DSA-OPM-2026-001",
        )
        _make_dsa(
            partner, status="renewed", version=2,
            reference="DSA-OPM-2026-001",
        )
        source = DataSharingAgreement.objects.get(
            reference="DSA-OPM-2026-001", version=1,
        )
        with pytest.raises(scope_service.ScopeEditError,
                           match="no active successor"):
            scope_service.renew(source, actor="op-1")


@pytest.mark.django_db
class TestRenewRejects:
    @pytest.mark.parametrize(
        "status_value",
        ["draft", "pending_signature", "suspended", "expired", "expiring"],
    )
    def test_rejects_non_renewable_status(self, partner, status_value):
        v1 = _make_dsa(partner, status=status_value)
        with pytest.raises(scope_service.ScopeEditError,
                           match="cannot be renewed"):
            scope_service.renew(v1, actor="op-1")


# ---------------------------------------------------------------------------
# /renew/ DRF surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRenewDrfAction:
    def test_post_on_active_returns_v2_draft(self, api, partner):
        c, _ = api
        v1 = _make_dsa(partner, status="active")
        r = c.post(f"{URL_DSAS}{v1.id}/renew/", {}, format="json")
        assert r.status_code == 200, r.data
        assert r.data["version"] == 2
        assert r.data["status"] == "draft"
        assert r.data["id"] != str(v1.id)

    def test_post_on_renewed_redirects(self, api, partner):
        c, _ = api
        v1 = _make_dsa(partner, status="renewed", version=1)
        v2 = _make_dsa(
            partner, status="active", version=2,
            reference="DSA-OPM-2026-001",
        )
        r = c.post(f"{URL_DSAS}{v1.id}/renew/", {}, format="json")
        assert r.status_code == 200
        assert r.data["id"] == str(v2.id)

    def test_post_on_draft_returns_400(self, api, partner):
        c, _ = api
        dsa = _make_dsa(partner, status="draft")
        r = c.post(f"{URL_DSAS}{dsa.id}/renew/", {}, format="json")
        assert r.status_code == 400
        assert "cannot be renewed" in r.data["detail"]


# ---------------------------------------------------------------------------
# Supersession via record_signature activation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSupersession:
    def test_v1_flips_to_renewed_when_v2_activates(self, partner):
        v1 = _make_dsa(partner, status="active", version=1)
        v2 = scope_service.renew(v1, actor="op-1")
        _sign_all(v2)

        v1.refresh_from_db()
        v2.refresh_from_db()
        assert v1.status == "renewed"
        assert v2.status == "active"

    def test_programme_fk_repointed(self, partner, programme):
        v1 = _make_dsa(partner, status="active", version=1)
        programme.dsa = v1
        programme.save(update_fields=["dsa"])

        v2 = scope_service.renew(v1, actor="op-1")
        _sign_all(v2)

        programme.refresh_from_db()
        assert programme.dsa_id == v2.id

    def test_multiple_programmes_all_repointed(self, partner):
        v1 = _make_dsa(partner, status="active", version=1)
        progs = []
        for code in ("PDM", "NUSAF", "SAGE"):
            p = Programme.objects.create(
                partner=partner, code=code, name=code,
                kind="cash_transfer", status="active", dsa=v1,
            )
            progs.append(p)

        v2 = scope_service.renew(v1, actor="op-1")
        _sign_all(v2)

        for p in progs:
            p.refresh_from_db()
            assert p.dsa_id == v2.id

    def test_emits_dsa_superseded_audit(self, partner, programme):
        v1 = _make_dsa(partner, status="active", version=1)
        programme.dsa = v1
        programme.save(update_fields=["dsa"])

        v2 = scope_service.renew(v1, actor="op-1")
        _sign_all(v2, actor="signer-1")

        ev = AuditEvent.objects.get(
            entity_type="dsa", action="dsa_superseded",
            entity_id=v1.id,
        )
        assert ev.field_changes["superseded_by"] == str(v2.id)
        assert ev.field_changes["new_version"] == 2
        assert ev.field_changes["programme_ids_repointed"] == [
            str(programme.id),
        ]

    def test_no_superseded_event_when_no_prior_active(self, partner):
        # First-ever DSA: activates without superseding anything.
        dsa = _make_dsa(partner, status="draft", version=1)
        _sign_all(dsa)

        assert not AuditEvent.objects.filter(
            entity_type="dsa", action="dsa_superseded",
        ).exists()

    def test_no_repoint_when_no_programmes_attached(self, partner):
        # v1 active but with no programmes attached → audit still
        # fires (the supersession itself happened) but the
        # programme_ids list is empty.
        v1 = _make_dsa(partner, status="active", version=1)
        v2 = scope_service.renew(v1, actor="op-1")
        _sign_all(v2)

        ev = AuditEvent.objects.get(
            entity_type="dsa", action="dsa_superseded", entity_id=v1.id,
        )
        assert ev.field_changes["programme_ids_repointed"] == []

    def test_independent_references_do_not_interfere(self, partner):
        # Two DSAs on different references should not affect each
        # other when one of them activates.
        a1 = _make_dsa(
            partner, status="active", version=1,
            reference="DSA-A-001",
        )
        b1 = _make_dsa(
            partner, status="active", version=1,
            reference="DSA-B-001",
        )
        a2 = scope_service.renew(a1, actor="op-1")
        _sign_all(a2)

        a1.refresh_from_db()
        b1.refresh_from_db()
        assert a1.status == "renewed"
        assert b1.status == "active"
