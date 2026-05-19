"""Tests for the partners app — US-S23-004 (Partner model)."""

from __future__ import annotations

import pytest

from apps.partners.models import Partner
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
