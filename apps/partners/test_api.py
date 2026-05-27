"""API tests for the partners module — US-S23-008."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.partners.models import Partner
from apps.reference_data.services import clear_resolver_cache

URL = "/api/v1/partners/"


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.fixture
def api(db):
    user_cls = get_user_model()
    u = user_cls.objects.create_superuser(
        username="partners-test", password="p",
    )
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def seeded_partners(db):
    rows = [
        ("OPM", "Office of the Prime Minister", "ministry",
         "social_protection", "active", "system"),
        ("UBOS", "Uganda Bureau of Statistics", "agency",
         "statistics", "active", "reference"),
        ("MoH", "Ministry of Health", "ministry",
         "health", "alert", "danger"),
        ("WFP", "World Food Programme", "multilateral",
         "humanitarian", "renewing", "update"),
        ("NIRA", "National Identification & Registration Authority",
         "agency", "identity", "provider", "identity"),
    ]
    return [
        Partner.objects.create(
            code=c, name=n, type=t, sector=s, status=st, tone=tn,
        )
        for c, n, t, s, st, tn in rows
    ]


@pytest.mark.django_db
class TestPartnerList:
    def test_list_returns_seeded_partners(self, api, seeded_partners):
        r = api.get(URL)
        assert r.status_code == 200
        codes = {p["code"] for p in r.data["results"]}
        assert codes == {"OPM", "UBOS", "MoH", "WFP", "NIRA"}

    def test_every_coded_field_carries_label(self, api, seeded_partners):
        r = api.get(URL)
        row = next(p for p in r.data["results"] if p["code"] == "OPM")
        assert row["type"] == "ministry"
        assert row["type_label"] == "Ministry"
        assert row["sector_label"] == "Social Protection"
        assert row["status_label"] == "Active"
        assert row["tone_label"] == "System"

    def test_q_filter(self, api, seeded_partners):
        r = api.get(URL, {"q": "health"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["MoH"]

    def test_type_filter(self, api, seeded_partners):
        r = api.get(URL, {"type": "multilateral"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["WFP"]

    def test_status_filter(self, api, seeded_partners):
        r = api.get(URL, {"status": "provider"})
        codes = [p["code"] for p in r.data["results"]]
        assert codes == ["NIRA"]


@pytest.mark.django_db
class TestPartnerRetrieve:
    def test_retrieve_by_id(self, api, seeded_partners):
        p = seeded_partners[0]
        r = api.get(f"{URL}{p.id}/")
        assert r.status_code == 200
        assert r.data["code"] == "OPM"
        assert r.data["type_label"] == "Ministry"


@pytest.mark.django_db
class TestPartnerWrite:
    def test_create_when_flag_enabled(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        r = api.post(URL, {
            "code": "BRAC", "name": "BRAC Uganda",
            "type": "ngo", "sector": "livelihoods",
            "status": "onboarding", "tone": "quality",
            "primary_email": "uganda@brac.net",
        }, format="json")
        assert r.status_code == 201, r.data
        assert r.data["code"] == "BRAC"
        assert r.data["type_label"] == "NGO"
        assert Partner.objects.filter(code="BRAC").exists()

    def test_create_forbidden_when_flag_disabled(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = False
        r = api.post(URL, {
            "code": "X", "name": "X", "type": "ngo",
            "status": "onboarding",
        }, format="json")
        assert r.status_code == 403
        assert "PARTNERS_MODULE_ENABLED" in str(r.data)

    def test_patch_updates_partner(self, api, settings, seeded_partners):
        settings.PARTNERS_MODULE_ENABLED = True
        p = next(x for x in seeded_partners if x.code == "OPM")
        r = api.patch(f"{URL}{p.id}/", {"note": "in-flight migration"},
                      format="json")
        assert r.status_code == 200
        assert r.data["note"] == "in-flight migration"


@pytest.mark.django_db
class TestDsaListFilters:
    """Filters added with the DSA management workspace: free-text
    search across reference + partner code/name, multi-status, and
    expiring-within-N-days for renewal triage.
    """

    URL_DSAS = "/api/v1/dsas/"

    @pytest.fixture
    def seeded_dsas(self, db, settings, seeded_partners):
        from datetime import date, timedelta

        from apps.partners.models import DataSharingAgreement
        settings.PARTNERS_MODULE_ENABLED = True
        opm   = next(p for p in seeded_partners if p.code == "OPM")
        ubos  = next(p for p in seeded_partners if p.code == "UBOS")
        wfp   = next(p for p in seeded_partners if p.code == "WFP")
        today = date.today()
        return {
            "opm_active": DataSharingAgreement.objects.create(
                reference="DSA-OPM-2026-001", partner=opm, status="active",
                effective_from=today, effective_to=today + timedelta(days=200),
            ),
            "ubos_draft": DataSharingAgreement.objects.create(
                reference="DSA-UBOS-2026-DRAFT", partner=ubos, status="draft",
            ),
            "wfp_expiring": DataSharingAgreement.objects.create(
                reference="DSA-WFP-2026-EXPIRY", partner=wfp, status="active",
                effective_from=today, effective_to=today + timedelta(days=20),
            ),
        }

    def test_q_filter_matches_reference_substring(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=WFP")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_q_filter_matches_partner_code(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=ubos")  # case-insensitive
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-UBOS-2026-DRAFT"}

    def test_q_filter_matches_partner_name_words(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?q=Food")  # World Food Programme
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_status_supports_comma_separated_list(self, api, seeded_dsas):
        r = api.get(f"{self.URL_DSAS}?status=draft,active")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {
            "DSA-OPM-2026-001",
            "DSA-UBOS-2026-DRAFT",
            "DSA-WFP-2026-EXPIRY",
        }

    def test_expiring_within_days_returns_only_dsas_inside_window(
        self, api, seeded_dsas,
    ):
        r = api.get(f"{self.URL_DSAS}?expiring_within_days=30")
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == {"DSA-WFP-2026-EXPIRY"}

    def test_expiring_within_days_bad_value_returns_today_window(
        self, api, seeded_dsas,
    ):
        # Garbage value clamps to 0 — empty for these DSAs (none expire
        # today). Asserts no 500, and the filter still applies (i.e.
        # the active-but-far-out DSA is excluded).
        r = api.get(f"{self.URL_DSAS}?expiring_within_days=abc")
        assert r.status_code == 200
        refs = {d["reference"] for d in r.data["results"]}
        assert refs == set()

    def test_status_all_is_a_no_op_not_a_literal_filter(
        self, api, seeded_dsas,
    ):
        # The DSA workspace passes `?status=all` (sometimes alongside
        # `q=`) to document intent. Treating "all" as a literal status
        # code would silently filter to zero rows since no DSA has
        # status="all" — that bug bit the version-history sidebar.
        r = api.get(f"{self.URL_DSAS}?status=all")
        refs = {d["reference"] for d in r.data["results"]}
        # All three seeded DSAs come back regardless of status.
        assert refs == {
            "DSA-OPM-2026-001",
            "DSA-UBOS-2026-DRAFT",
            "DSA-WFP-2026-EXPIRY",
        }


# --- US-S11-039 — DELETE Partner / DSA --------------------------------------

from datetime import date as _delete_date  # noqa: E402

from apps.partners.models import DataSharingAgreement, Programme  # noqa: E402
from apps.security.models import AuditEvent  # noqa: E402


@pytest.mark.django_db
class TestPartnerDelete:
    """DELETE /api/v1/partners/{id}/ — refuses when downstream rows
    (DSAs, Programmes, Contacts) still reference the partner. The
    response message names the blockers so the operator doesn't have
    to chase a generic FK error."""

    def test_delete_unreferenced_partner_succeeds(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="GHOST", name="Will be deleted", type="ministry",
            sector="social_protection", status="onboarding", tone="neutral",
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 204
        assert not Partner.objects.filter(id=p.id).exists()
        ev = AuditEvent.objects.filter(
            action="partners.partner.deleted", entity_id=str(p.id),
        ).first()
        assert ev is not None

    def test_delete_partner_with_dsa_is_rejected(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="BLOCKED", name="Has a DSA", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        DataSharingAgreement.objects.create(
            partner=p, reference="DSA-BLOCKED-001",
            status="draft", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 400
        # US-S11-040 — draft DSAs are non-terminal and still block.
        # Message changed to "active DSA(s)" wording.
        assert "1 active DSA(s)" in r.json()["detail"]
        assert Partner.objects.filter(id=p.id).exists()

    def test_delete_partner_with_programme_is_rejected(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="PROGGED", name="Has a programme", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        Programme.objects.create(
            partner=p, code="PG-01", name="Active programme",
            kind="cash_transfer", status="active",
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 400
        assert "1 active programme(s)" in r.json()["detail"]

    def test_delete_gated_by_write_flag(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = False
        p = Partner.objects.create(
            code="GATED", name="Gated", type="ministry",
            sector="social_protection", status="onboarding", tone="neutral",
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 403


@pytest.mark.django_db
class TestDsaDelete:
    """DELETE /api/v1/dsas/{id}/ — drafts only. Active+ DSAs use
    renew/edit-scope/suspend so signature + audit chain doesn't
    orphan."""

    def test_delete_draft_succeeds_with_audit(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="DEL1", name="X", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-DEL-001", status="draft", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"/api/v1/dsas/{dsa.id}/")
        assert r.status_code == 204
        assert not DataSharingAgreement.objects.filter(id=dsa.id).exists()
        ev = AuditEvent.objects.filter(
            action="partners.dsa.deleted", entity_id=str(dsa.id),
        ).first()
        assert ev is not None
        assert ev.field_changes.get("reference") == "DSA-DEL-001"

    def test_delete_active_dsa_is_rejected(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="DEL2", name="Y", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-DEL-002", status="active", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"/api/v1/dsas/{dsa.id}/")
        assert r.status_code == 400
        assert "status is 'active'" in r.json()["detail"]
        assert DataSharingAgreement.objects.filter(id=dsa.id).exists()


# --- US-S11-040 — DSA suspend + cascade Partner delete --------------------

@pytest.mark.django_db
class TestDsaSuspend:
    """POST /api/v1/dsas/{id}/suspend/ — lifecycle close for active /
    expired agreements. Audit-bearing. Refused on draft (use Delete)
    and on already-terminal states."""

    def test_suspend_active_succeeds(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="SUS1", name="A", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-SUS-001", status="active", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.post(
            f"/api/v1/dsas/{dsa.id}/suspend/",
            {"reason": "partner withdrew"}, format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["status"] == "suspended"
        dsa.refresh_from_db()
        assert dsa.status == "suspended"
        ev = AuditEvent.objects.filter(
            action="partners.dsa.suspended", entity_id=str(dsa.id),
        ).first()
        assert ev is not None
        assert ev.field_changes["from_status"] == "active"
        assert ev.field_changes["to_status"] == "suspended"
        assert "withdrew" in ev.reason

    def test_suspend_expired_succeeds(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="SUS2", name="B", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-SUS-002", status="expired", version=1,
            effective_from=_delete_date(2024, 1, 1),
            effective_to=_delete_date(2025, 1, 1),
        )
        r = api.post(f"/api/v1/dsas/{dsa.id}/suspend/", {"reason": "x"}, format="json")
        assert r.status_code == 200

    def test_suspend_draft_is_rejected(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="SUS3", name="C", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-SUS-003", status="draft", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.post(f"/api/v1/dsas/{dsa.id}/suspend/", {"reason": "x"}, format="json")
        assert r.status_code == 400
        assert "status is 'draft'" in r.json()["detail"]


@pytest.mark.django_db
class TestPartnerDeleteCascade:
    """US-S11-040 — Partner delete cascades through terminal DSAs +
    closed Programmes + all Contacts; only ACTIVE downstream rows
    still block. Lets operators wind down a partnership end-to-end."""

    def test_cascade_through_suspended_dsa(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="WIND1", name="Wind down", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        dsa = DataSharingAgreement.objects.create(
            partner=p, reference="DSA-WIND-001", status="suspended", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 204, r.content
        assert not Partner.objects.filter(id=p.id).exists()
        assert not DataSharingAgreement.objects.filter(id=dsa.id).exists()
        ev = AuditEvent.objects.filter(
            action="partners.partner.deleted", entity_id=str(p.id),
        ).first()
        assert ev is not None
        assert "DSA-WIND-001" in ev.field_changes["cascaded_dsa_refs"]

    def test_cascade_through_closed_programme(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="WIND2", name="Wind down 2", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        prog = Programme.objects.create(
            partner=p, code="WIND-PG-01", name="Closed cohort",
            kind="cash_transfer", status="closed",
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 204
        assert not Programme.objects.filter(id=prog.id).exists()

    def test_active_dsa_still_blocks(self, api, settings):
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="STILL", name="Still live", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        DataSharingAgreement.objects.create(
            partner=p, reference="DSA-STILL-001", status="active", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 400
        assert "1 active DSA(s)" in r.json()["detail"]
        assert Partner.objects.filter(id=p.id).exists()

    def test_mixed_terminal_and_active_blocks_only_on_active(self, api, settings):
        # Operator wound down DSA-A (suspended) but DSA-B is still
        # active — delete must still refuse, only naming the active.
        settings.PARTNERS_MODULE_ENABLED = True
        p = Partner.objects.create(
            code="MIX", name="Mixed", type="ministry",
            sector="social_protection", status="active", tone="primary",
        )
        DataSharingAgreement.objects.create(
            partner=p, reference="DSA-MIX-A", status="suspended", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        DataSharingAgreement.objects.create(
            partner=p, reference="DSA-MIX-B", status="active", version=1,
            effective_from=_delete_date(2026, 1, 1),
            effective_to=_delete_date(2027, 1, 1),
        )
        r = api.delete(f"{URL}{p.id}/")
        assert r.status_code == 400
        assert "1 active DSA(s)" in r.json()["detail"]
        # Both DSAs survive — no partial cleanup.
        assert DataSharingAgreement.objects.filter(partner=p).count() == 2
