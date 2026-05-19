"""Tests for the partners app — US-S23-004 (Partner model)."""

from __future__ import annotations

import pytest

from apps.partners.models import Partner, PartnerContact, Programme
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
