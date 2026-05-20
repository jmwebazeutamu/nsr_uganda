"""DSA scope-edit + clone tests — US-S27-003 / ADR-0016.

Covers both the service layer (`apps.partners.services.scope`) and
the DRF surface (`POST /api/v1/dsas/{id}/edit-scope/`). The two
paths differ only in I/O: the service does the work, the viewset
wraps it in HTTP semantics and audit-scoped error mapping.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import (
    DataSharingAgreement,
    Partner,
    Programme,
)
from apps.partners.services import scope as scope_service
from apps.reference_data.models import GeographicUnit
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
    u = user_cls.objects.create_superuser(username="scope-editor", password="p")
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
def gu_a(db):
    return GeographicUnit.objects.create(
        level="sub_region", code="SR-A", name="Karamoja",
        effective_from=date(2026, 1, 1),
    )


@pytest.fixture
def gu_b(db):
    return GeographicUnit.objects.create(
        level="sub_region", code="SR-B", name="Acholi",
        effective_from=date(2026, 1, 1),
    )


@pytest.fixture
def programme(db, partner):
    return Programme.objects.create(
        partner=partner, code="PDM", name="PDM",
        kind="cash_transfer", status="active",
    )


def _make_dsa(
    partner, *, status="draft", version=1, reference="DSA-OPM-2026-001",
    field_scope=None, monthly_row_budget=100_000,
):
    return DataSharingAgreement.objects.create(
        reference=reference, partner=partner, version=version,
        status=status,
        field_scope=field_scope or {"Identifiers": True, "PMT": False},
        entities_scope={"household": True, "member": False},
        monthly_row_budget=monthly_row_budget,
        sensitive_data_handling="none", retention_days=180,
        classification="restricted",
        breach_sla_hours=72,
    )


# ---------------------------------------------------------------------------
# Service-level behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEditScopeDraft:
    def test_applies_scalar_changes_in_place(self, partner):
        dsa = _make_dsa(partner)
        before_id = dsa.id
        before_version = dsa.version

        result = scope_service.edit_scope(
            dsa, actor="op-1",
            monthly_row_budget=250_000,
            sensitive_data_handling="specific",
            classification="confidential",
        )

        assert result.id == before_id
        assert result.version == before_version
        assert result.status == "draft"
        assert result.monthly_row_budget == 250_000
        assert result.sensitive_data_handling == "specific"
        assert result.classification == "confidential"

    def test_applies_field_scope_dict(self, partner):
        dsa = _make_dsa(partner)
        result = scope_service.edit_scope(
            dsa, actor="op-1",
            field_scope={"Identifiers": True, "PMT": True, "Health": True},
        )
        assert result.field_scope == {
            "Identifiers": True, "PMT": True, "Health": True,
        }

    def test_resets_geographic_scope_m2m(self, partner, gu_a, gu_b):
        dsa = _make_dsa(partner)
        dsa.geographic_scope.add(gu_a)
        assert list(dsa.geographic_scope.all()) == [gu_a]

        result = scope_service.edit_scope(
            dsa, actor="op-1",
            geographic_scope_ids=[gu_b.id],
        )
        assert list(result.geographic_scope.all()) == [gu_b]

    def test_ignores_unknown_keys(self, partner):
        dsa = _make_dsa(partner)
        result = scope_service.edit_scope(
            dsa, actor="op-1",
            partner=99,         # not in allowlist
            status="active",    # not in allowlist
            monthly_row_budget=42,
        )
        # The two ignored keys are no-ops; budget got applied.
        assert result.monthly_row_budget == 42
        assert result.status == "draft"

    def test_emits_dsa_scope_changed_with_diff(self, partner):
        dsa = _make_dsa(partner, monthly_row_budget=100_000)
        scope_service.edit_scope(
            dsa, actor="op-1",
            monthly_row_budget=500_000,
            classification="public",
        )
        ev = AuditEvent.objects.filter(
            entity_type="dsa", action="dsa_scope_changed",
            entity_id=str(dsa.id),
        ).get()
        assert ev.field_changes["editor"] == "op-1"
        assert ev.field_changes["version"] == 1
        assert ev.field_changes["before"]["monthly_row_budget"] == 100_000
        assert ev.field_changes["after"]["monthly_row_budget"] == 500_000
        assert ev.field_changes["before"]["classification"] == "restricted"
        assert ev.field_changes["after"]["classification"] == "public"


@pytest.mark.django_db
class TestEditScopeActive:
    def test_clones_to_v_plus_one_draft(self, partner):
        v1 = _make_dsa(partner, status="active", version=1)
        result = scope_service.edit_scope(
            v1, actor="op-1", monthly_row_budget=999_999,
        )

        assert result.id != v1.id
        assert result.version == 2
        assert result.status == "draft"
        assert result.reference == v1.reference
        assert result.partner_id == v1.partner_id

    def test_original_v1_untouched(self, partner):
        v1 = _make_dsa(partner, status="active", monthly_row_budget=100_000)
        scope_service.edit_scope(
            v1, actor="op-1", monthly_row_budget=999_999,
        )
        v1.refresh_from_db()
        assert v1.status == "active"
        assert v1.version == 1
        assert v1.monthly_row_budget == 100_000

    def test_clone_inherits_then_overrides(self, partner):
        v1 = _make_dsa(
            partner, status="active",
            field_scope={"Identifiers": True, "PMT": False},
            monthly_row_budget=100_000,
        )
        v2 = scope_service.edit_scope(
            v1, actor="op-1",
            monthly_row_budget=500_000,
            # field_scope NOT supplied → should be copied verbatim
        )
        assert v2.monthly_row_budget == 500_000
        assert v2.field_scope == {"Identifiers": True, "PMT": False}

    def test_clone_preserves_programmes_m2m(self, partner, programme):
        v1 = _make_dsa(partner, status="active")
        v1.programmes.add(programme)

        v2 = scope_service.edit_scope(
            v1, actor="op-1", monthly_row_budget=1,
        )
        assert list(v2.programmes.all()) == [programme]

    def test_clone_preserves_geographic_scope_m2m(self, partner, gu_a, gu_b):
        v1 = _make_dsa(partner, status="active")
        v1.geographic_scope.add(gu_a, gu_b)

        v2 = scope_service.edit_scope(
            v1, actor="op-1", monthly_row_budget=1,
        )
        assert set(v2.geographic_scope.all()) == {gu_a, gu_b}

    def test_clone_does_not_repoint_programme_fk(self, partner, programme):
        # Per ADR-0016 §"Decision 4", Programme.dsa FK only re-points
        # when v(N+1) reaches `status="active"`. Edit-scope just
        # clones — the FK on v(N) programmes stays pointing at v(N).
        v1 = _make_dsa(partner, status="active")
        programme.dsa = v1
        programme.save(update_fields=["dsa"])

        scope_service.edit_scope(v1, actor="op-1", monthly_row_budget=1)
        programme.refresh_from_db()
        assert programme.dsa_id == v1.id

    def test_clone_signatures_empty(self, partner):
        v1 = _make_dsa(partner, status="active")
        v2 = scope_service.edit_scope(v1, actor="op-1", monthly_row_budget=1)
        assert not v2.signatures.exists()

    def test_clone_effective_dates_null(self, partner):
        v1 = _make_dsa(partner, status="active")
        v1.effective_from = date(2026, 1, 1)
        v1.effective_to = date(2026, 12, 31)
        v1.save(update_fields=["effective_from", "effective_to"])

        v2 = scope_service.edit_scope(v1, actor="op-1", monthly_row_budget=1)
        assert v2.effective_from is None
        assert v2.effective_to is None
        assert v2.signed_at is None

    def test_emits_clone_and_scope_changed_audits(self, partner):
        v1 = _make_dsa(partner, status="active", monthly_row_budget=100_000)
        v2 = scope_service.edit_scope(
            v1, actor="op-1", monthly_row_budget=500_000,
        )

        clone_ev = AuditEvent.objects.get(
            entity_type="dsa", action="clone", entity_id=str(v2.id),
        )
        assert clone_ev.field_changes["source_dsa_id"] == str(v1.id)
        assert clone_ev.field_changes["source_version"] == 1
        assert clone_ev.field_changes["new_version"] == 2

        scope_ev = AuditEvent.objects.get(
            entity_type="dsa", action="dsa_scope_changed",
            entity_id=str(v2.id),
        )
        assert scope_ev.field_changes["before"]["monthly_row_budget"] == 100_000
        assert scope_ev.field_changes["after"]["monthly_row_budget"] == 500_000
        assert scope_ev.field_changes["version"] == 2

        # No scope_changed event on the original v(N).
        assert not AuditEvent.objects.filter(
            entity_type="dsa", action="dsa_scope_changed",
            entity_id=str(v1.id),
        ).exists()


@pytest.mark.django_db
class TestEditScopeRejects:
    @pytest.mark.parametrize(
        "status_value",
        ["pending_signature", "suspended", "expired", "renewed"],
    )
    def test_rejects_non_editable_status(self, partner, status_value):
        dsa = _make_dsa(partner, status=status_value)
        with pytest.raises(scope_service.ScopeEditError,
                           match="cannot be scope-edited"):
            scope_service.edit_scope(
                dsa, actor="op-1", monthly_row_budget=1,
            )


# ---------------------------------------------------------------------------
# clone_to_draft (exposed for US-S27-005 renewal)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCloneToDraft:
    def test_clone_basic_shape(self, partner):
        v1 = _make_dsa(partner, status="active")
        v2 = scope_service.clone_to_draft(v1, actor="op-1")
        assert v2.reference == v1.reference
        assert v2.version == 2
        assert v2.status == "draft"
        assert v2.partner_id == v1.partner_id

    def test_audit_event_has_source_pointers(self, partner):
        v1 = _make_dsa(partner, status="active")
        v2 = scope_service.clone_to_draft(
            v1, actor="op-1", reason="renewal probe",
        )
        ev = AuditEvent.objects.get(
            entity_type="dsa", action="clone", entity_id=str(v2.id),
        )
        assert ev.reason == "renewal probe"
        assert ev.field_changes["source_dsa_id"] == str(v1.id)


# ---------------------------------------------------------------------------
# DRF surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEditScopeDrfAction:
    def test_post_on_draft_returns_updated(self, api, partner):
        c, _ = api
        dsa = _make_dsa(partner)
        r = c.post(
            f"{URL_DSAS}{dsa.id}/edit-scope/",
            {"monthly_row_budget": 555_555}, format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["id"] == str(dsa.id)
        assert r.data["monthly_row_budget"] == 555_555

    def test_post_on_active_returns_new_draft(self, api, partner):
        c, _ = api
        v1 = _make_dsa(partner, status="active")
        r = c.post(
            f"{URL_DSAS}{v1.id}/edit-scope/",
            {"monthly_row_budget": 111}, format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["id"] != str(v1.id)
        assert r.data["version"] == 2
        assert r.data["status"] == "draft"
        assert r.data["monthly_row_budget"] == 111

    def test_post_on_suspended_returns_400(self, api, partner):
        c, _ = api
        dsa = _make_dsa(partner, status="suspended")
        r = c.post(
            f"{URL_DSAS}{dsa.id}/edit-scope/",
            {"monthly_row_budget": 1}, format="json",
        )
        assert r.status_code == 400
        assert "cannot be scope-edited" in r.data["detail"]


@pytest.mark.django_db
class TestPatchRejectsActive:
    def test_patch_active_returns_400_with_pointer(self, api, partner):
        c, _ = api
        dsa = _make_dsa(partner, status="active")
        r = c.patch(
            f"{URL_DSAS}{dsa.id}/",
            {"monthly_row_budget": 999}, format="json",
        )
        assert r.status_code == 400
        assert "edit-scope" in r.data["detail"]
        assert r.data["edit_scope_url"].endswith(
            f"/api/v1/dsas/{dsa.id}/edit-scope/",
        )
        # And no mutation happened.
        dsa.refresh_from_db()
        assert dsa.monthly_row_budget == 100_000

    def test_patch_draft_still_works(self, api, partner):
        c, _ = api
        dsa = _make_dsa(partner, status="draft")
        r = c.patch(
            f"{URL_DSAS}{dsa.id}/",
            {"monthly_row_budget": 7}, format="json",
        )
        assert r.status_code == 200, r.data
        dsa.refresh_from_db()
        assert dsa.monthly_row_budget == 7
