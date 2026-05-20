"""Exercise the US-S26-004 lift logic with synthetic data.

The data migration runs against an empty referral.Programme table
in dev. This test recreates the three attribution paths in code by
calling the lift helpers directly:

  1. existing canonical row → dedup (no new row)
  2. code-prefix Partner match → lifted under that Partner
  3. neither → lifted under synthesized 'GoU-Legacy' Partner

It also asserts the webhook cleartext lands in the encrypted column
and dsa_reference_legacy is carried over.
"""

from __future__ import annotations

import pytest
from apps.partners.models import Partner
from apps.partners.models import Programme as CanonicalProgramme
from apps.referral.models import Programme as ReferralProgramme


def _lift_helpers():
    """Import the migration's helpers so the test exercises the
    same code path the migration runs (without re-running the
    migration itself)."""
    import importlib
    mod = importlib.import_module(
        "apps.referral.migrations.0003_lift_referral_programmes_to_partners",
    )
    return mod


@pytest.mark.django_db
def test_lift_dedups_existing_canonical(settings):
    """Step 1 of ADR-0015 §Decision 2: if a partners.Programme with
    the same code already exists, the referral row is dropped without
    lifting."""
    opm = Partner.objects.create(
        code="OPM", name="OPM", type="ministry", status="active",
    )
    CanonicalProgramme.objects.create(
        partner=opm, code="OPM-PDM", name="PDM (canonical)",
        kind="cash_transfer",
    )
    ReferralProgramme.objects.create(
        code="OPM-PDM", name="PDM (referral)",
        webhook_url="https://opm.example/incoming",
        webhook_secret="secret-from-referral",
        dsa_reference="DSA-OPM-PDM-2026-001",
    )

    mod = _lift_helpers()
    from django.apps import apps as django_apps
    mod._lift(django_apps, schema_editor=None)

    # Still only one canonical row (the existing one), unchanged.
    rows = CanonicalProgramme.objects.filter(code="OPM-PDM")
    assert rows.count() == 1
    assert rows.first().name == "PDM (canonical)"


@pytest.mark.django_db
def test_lift_attributes_via_code_prefix(settings):
    """Step 2: code-prefix match — referral.Programme code 'OPM-PDM'
    attributes to Partner code 'OPM'."""
    opm = Partner.objects.create(
        code="OPM", name="OPM", type="ministry", status="active",
    )
    ReferralProgramme.objects.create(
        code="OPM-PDM", name="Parish Development Model",
        webhook_url="https://opm.example/incoming",
        webhook_secret="secret-from-referral",
        dsa_reference="DSA-OPM-PDM-2026-001",
        is_active=True,
    )

    mod = _lift_helpers()
    from django.apps import apps as django_apps
    mod._lift(django_apps, schema_editor=None)

    canonical = CanonicalProgramme.objects.get(code="OPM-PDM")
    assert canonical.partner_id == opm.id
    assert canonical.status == "active"
    assert canonical.dsa_reference_legacy == "DSA-OPM-PDM-2026-001"
    # The encrypted column round-trips the cleartext.
    assert canonical.webhook_secret_encrypted == b"secret-from-referral"


@pytest.mark.django_db
def test_lift_falls_back_to_legacy_partner(settings):
    """Step 3: no canonical, no prefix match — synthesize GoU-Legacy
    and attribute there."""
    # No 'OPM' Partner created. The referral code has no hyphen either,
    # so the prefix walk yields no match.
    ReferralProgramme.objects.create(
        code="STANDALONE-PILOT", name="Standalone pilot",
        webhook_url="", webhook_secret="",
        is_active=False,
    )

    mod = _lift_helpers()
    from django.apps import apps as django_apps
    mod._lift(django_apps, schema_editor=None)

    legacy = Partner.objects.get(code="GoU-LEGACY")
    assert legacy.status == "provider"

    canonical = CanonicalProgramme.objects.get(code="STANDALONE-PILOT")
    assert canonical.partner_id == legacy.id
    assert canonical.status == "draft"  # is_active=False → draft
    assert canonical.webhook_secret_encrypted is None  # no secret to lift


@pytest.mark.django_db
def test_lift_is_idempotent(settings):
    """Running _lift twice produces the same canonical rows; no
    duplicates."""
    Partner.objects.create(
        code="OPM", name="OPM", type="ministry", status="active",
    )
    ReferralProgramme.objects.create(
        code="OPM-PDM", name="PDM",
        webhook_url="", webhook_secret="x",
        is_active=True,
    )

    mod = _lift_helpers()
    from django.apps import apps as django_apps
    mod._lift(django_apps, schema_editor=None)
    mod._lift(django_apps, schema_editor=None)

    assert CanonicalProgramme.objects.filter(code="OPM-PDM").count() == 1
