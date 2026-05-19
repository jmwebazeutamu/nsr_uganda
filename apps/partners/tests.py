"""Tests for the partners app — US-S23-004 (Partner model)."""

from __future__ import annotations

from datetime import UTC

import pytest

from apps.partners.models import (
    DataSharingAgreement,
    DsaSignature,
    Partner,
    PartnerContact,
    PartnerUsageDaily,
    Programme,
)
from apps.reference_data.services import clear_resolver_cache


@pytest.fixture(autouse=True)
def _flush():
    clear_resolver_cache()
    yield
    clear_resolver_cache()


@pytest.mark.django_db
class TestPartnerModel:
    def test_create_partner_with_codes(self):
        p = Partner.objects.create(
            code="OPM",
            name="Office of the Prime Minister",
            type="ministry",
            sector="social_protection",
            status="active",
            tone="system",
            primary_email="ps@opm.go.ug",
        )
        assert p.id  # ULID assigned
        assert p.code == "OPM"
        assert str(p) == "OPM (Office of the Prime Minister)"

    def test_label_methods_attached(self):
        p = Partner.objects.create(
            code="OPM", name="OPM", type="ministry",
            sector="social_protection", status="active", tone="system",
        )
        # Methods auto-attached by AppConfig.ready against the
        # partners choice_field_map (US-S23-004).
        assert p.get_type_label() == "Ministry"
        assert p.get_sector_label() == "Social Protection"
        assert p.get_status_label() == "Active"
        assert p.get_tone_label() == "System"

    def test_unknown_code_returns_raw(self):
        p = Partner.objects.create(
            code="X", name="Y", type="not_a_real_type",
            status="onboarding",
        )
        # Resolver logs unmapped_code WARNING but returns the raw value.
        assert p.get_type_label() == "not_a_real_type"

    def test_code_unique(self):
        from django.db.utils import IntegrityError
        Partner.objects.create(code="OPM", name="X", type="ministry")
        with pytest.raises(IntegrityError):
            Partner.objects.create(code="OPM", name="Z", type="ministry")


@pytest.mark.django_db
class TestE001CoversPartnerFields:
    def test_partner_fields_pass_e001(self):
        # The choice_field_map registers Partner.type, .sector, .status,
        # .tone. E001 walks the registry; clean tree => no errors.
        from apps.data_management.checks import (
            check_no_textchoices_on_mapped_fields,
        )
        errors = list(check_no_textchoices_on_mapped_fields(app_configs=None))
        assert errors == []

    def test_partner_fields_are_registered(self):
        from apps.partners.choice_field_map import MODEL_FIELDS
        assert set(MODEL_FIELDS["Partner"]) == {
            "type", "sector", "status", "tone",
        }


@pytest.mark.django_db
class TestPartnerContact:
    def test_unique_role_per_partner(self):
        from django.db.utils import IntegrityError
        p = Partner.objects.create(code="X", name="X", type="ministry")
        PartnerContact.objects.create(
            partner=p, role="authorised_signatory",
            full_name="Dr. Atim Florence", email="a@x.go.ug",
        )
        with pytest.raises(IntegrityError):
            PartnerContact.objects.create(
                partner=p, role="authorised_signatory",
                full_name="Someone Else", email="b@x.go.ug",
            )

    def test_role_label_resolves(self):
        p = Partner.objects.create(code="X", name="X", type="ministry")
        c = PartnerContact.objects.create(
            partner=p, role="partner_dpo",
            full_name="Mukasa Catherine", email="dpo@x.go.ug",
        )
        assert c.get_role_label() == "Data Protection Officer (Partner)"


@pytest.mark.django_db
class TestProgramme:
    def test_kind_and_status_labels_resolve(self):
        p = Partner.objects.create(code="X", name="X", type="ngo")
        prog = Programme.objects.create(
            partner=p, name="Karamoja Cash 2026",
            kind="cash_transfer", status="active",
        )
        assert prog.get_kind_label() == "Cash transfer"
        assert prog.get_status_label() == "Active"

    def test_geographic_units_m2m(self):
        from datetime import date

        from apps.reference_data.models import GeographicUnit
        gu = GeographicUnit.objects.create(
            level="sub_region", code="SR-PROG-1", name="Karamoja",
            effective_from=date(2026, 1, 1),
        )
        p = Partner.objects.create(code="P", name="P", type="ngo")
        prog = Programme.objects.create(
            partner=p, name="X", kind="cash_transfer", status="active",
        )
        prog.geographic_units.add(gu)
        assert list(prog.geographic_units.all()) == [gu]


@pytest.mark.django_db
class TestDataSharingAgreement:
    def _partner(self):
        return Partner.objects.create(code="X", name="X", type="ministry")

    def test_create_with_codes_and_labels(self):
        p = self._partner()
        dsa = DataSharingAgreement.objects.create(
            reference="DSA-X-2026-001", partner=p,
            status="draft", sensitive_data_handling="none",
            monthly_row_budget=100_000,
        )
        assert dsa.get_status_label() == "Draft"
        assert dsa.get_sensitive_data_handling_label() == "None"

    def test_effective_window_constraint(self):
        from datetime import date

        from django.db.utils import IntegrityError
        p = self._partner()
        with pytest.raises(IntegrityError):
            DataSharingAgreement.objects.create(
                reference="DSA-X-2026-002", partner=p,
                status="draft",
                effective_from=date(2026, 5, 19),
                effective_to=date(2026, 5, 18),  # before
            )

    def test_reference_version_unique(self):
        from django.db.utils import IntegrityError
        p = self._partner()
        DataSharingAgreement.objects.create(
            reference="DSA-X-2026-001", partner=p, version=1, status="draft",
        )
        with pytest.raises(IntegrityError):
            DataSharingAgreement.objects.create(
                reference="DSA-X-2026-001", partner=p, version=1,
                status="draft",
            )

    def test_provider_partners_allow_null_budget(self):
        # ADR-0011 decision 3: provider-status partners (NIRA) skip
        # budget/usage. The column is nullable; create one to prove.
        p = self._partner()
        dsa = DataSharingAgreement.objects.create(
            reference="DSA-X-PROV", partner=p, status="active",
            monthly_row_budget=None,
        )
        assert dsa.monthly_row_budget is None


@pytest.mark.django_db
class TestDsaSignature:
    def _dsa(self):
        p = Partner.objects.create(code="X", name="X", type="ministry")
        return DataSharingAgreement.objects.create(
            reference="DSA-X-2026-001", partner=p, status="draft",
        )

    def test_sequence_order_unique_per_dsa(self):
        from django.db.utils import IntegrityError
        dsa = self._dsa()
        DsaSignature.objects.create(
            dsa=dsa, sequence_order=1,
            signer_role="partner_auth_signatory",
            signer_email="a@x.go.ug", method="docusign", status="pending",
        )
        with pytest.raises(IntegrityError):
            DsaSignature.objects.create(
                dsa=dsa, sequence_order=1,
                signer_role="nsr_unit_lead",
                signer_email="b@nsr.go.ug", method="in_console",
                status="pending",
            )

    def test_signer_email_unique_per_dsa(self):
        from django.db.utils import IntegrityError
        dsa = self._dsa()
        DsaSignature.objects.create(
            dsa=dsa, sequence_order=1,
            signer_role="partner_auth_signatory",
            signer_email="a@x.go.ug", method="docusign", status="pending",
        )
        with pytest.raises(IntegrityError):
            DsaSignature.objects.create(
                dsa=dsa, sequence_order=2,
                signer_role="nsr_unit_lead",
                signer_email="a@x.go.ug",  # same email — self-sign-off
                method="in_console", status="pending",
            )

    def test_signature_labels_resolve(self):
        dsa = self._dsa()
        sig = DsaSignature.objects.create(
            dsa=dsa, sequence_order=1,
            signer_role="dpo",
            signer_email="dpo@mglsd.go.ug", method="in_console",
            status="signed",
        )
        assert sig.get_signer_role_label() == "Data Protection Officer (MGLSD)"
        assert sig.get_method_label() == "In-console"
        assert sig.get_status_label() == "Signed"


@pytest.mark.django_db
class TestPartnerUsageDaily:
    def test_unique_day_per_partner(self):
        from datetime import date

        from django.db.utils import IntegrityError
        p = Partner.objects.create(code="OPM", name="OPM", type="ministry")
        PartnerUsageDaily.objects.create(
            partner=p, day=date(2026, 5, 19),
            rows_delivered=1000, requests_count=3,
        )
        with pytest.raises(IntegrityError):
            PartnerUsageDaily.objects.create(
                partner=p, day=date(2026, 5, 19),
                rows_delivered=999, requests_count=1,
            )


@pytest.mark.django_db
class TestActivityProjection:
    def test_unknown_action_falls_back_to_status_change(self):
        from datetime import datetime

        from apps.partners.services.activity import project
        from apps.security.models import AuditEvent

        evt = AuditEvent(
            action="random_unmapped_action",
            entity_type="partner", entity_id="X",
            actor_id="tester", reason="r",
            occurred_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        )
        out = project(evt, partner_code="OPM")
        assert out.kind == "partner_status_change"
        assert out.severity_tone == "neutral"

    def test_known_action_maps_to_kind(self):
        from datetime import datetime

        from apps.partners.services.activity import project
        from apps.security.models import AuditEvent

        evt = AuditEvent(
            action="breach_detected",
            entity_type="dsa", entity_id="d",
            actor_id="system", reason="30d > budget",
            occurred_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        )
        out = project(evt, partner_code="MoH")
        assert out.kind == "dsa_breach"
        assert out.severity_tone == "danger"
        assert out.partner_code == "MoH"
