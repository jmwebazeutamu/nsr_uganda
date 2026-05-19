"""US-S24-002 — Lift DRS-local Partner + DSA rows into apps.partners.

For every apps.data_requests.DataSharingAgreement, idempotently
create the canonical apps.partners.DataSharingAgreement (and
apps.partners.Partner) row. The canonical row reuses the same ULID
as the DRS-local row so the FK swap in 0003 can re-target the
column without re-mapping IDs.

Per ADR-0013 §"Migration policy" the legacy `allowed_scopes` JSON
maps onto the canonical fields:

    allowed_scopes.fields              → field_scope dict (group → True)
    allowed_scopes.sub_region_codes    → geographic_scope M2M (resolved by code)
    allowed_scopes.programme_codes     → entities_scope.programmes_allowed
    allowed_scopes.max_rows_per_request → monthly_row_budget

Forward-only per ADR-0003. The reverse hook is a no-op (deleting
canonical rows that may already have been edited via the wizard
would lose audit history).
"""

from __future__ import annotations

from django.db import migrations

# Field defaults that the legacy schema didn't carry.
_PARTNER_DEFAULTS = {
    "type": "agency",       # closest equivalent; can be edited via admin
    "tone": "neutral",
    "sector": "",
}
_DSA_DEFAULTS = {
    "sensitive_data_handling": "none",
    "retention_days": 180,
    "breach_sla_hours": 72,
    "classification": "",
    "version": 1,
}


def _lift(apps, schema_editor):
    DrsDsa = apps.get_model("data_requests", "DataSharingAgreement")
    PartnerModel = apps.get_model("partners", "Partner")
    DsaModel = apps.get_model("partners", "DataSharingAgreement")
    GeographicUnit = apps.get_model("reference_data", "GeographicUnit")

    for old_dsa in DrsDsa.objects.select_related("partner"):
        old_partner = old_dsa.partner

        # 1. Canonical Partner: get-or-create by code.
        canonical_partner, _ = PartnerModel.objects.get_or_create(
            code=old_partner.code,
            defaults={
                "name": old_partner.name,
                "primary_email": old_partner.contact_email or "",
                "status": (
                    "active" if old_partner.status == "active" else "suspended"
                ),
                **_PARTNER_DEFAULTS,
            },
        )

        # 2. Map allowed_scopes → canonical shape.
        scopes = old_dsa.allowed_scopes or {}
        legacy_fields = scopes.get("fields") or []
        field_scope = {}
        for f in legacy_fields:
            group, _, _leaf = (f or "").partition(".")
            if group:
                field_scope[group] = True

        entities_scope = {
            "programmes_allowed": scopes.get("programme_codes") or [],
        }
        max_rows = scopes.get("max_rows_per_request")
        sub_region_codes = scopes.get("sub_region_codes") or []

        # 3. Canonical DSA: get-or-create by (reference, version=1).
        # Reusing the DRS-local ULID means the FK swap in 0003 keeps
        # working without a separate id-remap pass.
        canonical_dsa, was_new = DsaModel.objects.get_or_create(
            reference=old_dsa.reference,
            version=_DSA_DEFAULTS["version"],
            defaults={
                "id": old_dsa.id,
                "partner": canonical_partner,
                "status": old_dsa.status,
                "effective_from": old_dsa.valid_from,
                "effective_to": old_dsa.valid_to,
                "monthly_row_budget": max_rows,
                "entities_scope": entities_scope,
                "field_scope": field_scope,
                **{k: v for k, v in _DSA_DEFAULTS.items() if k != "version"},
            },
        )

        # 4. Attach geographic scope by sub_region code lookup.
        if was_new and sub_region_codes:
            gus = list(
                GeographicUnit.objects.filter(
                    level="sub_region",
                    code__in=sub_region_codes,
                ),
            )
            if gus:
                canonical_dsa.geographic_scope.add(*gus)


class Migration(migrations.Migration):

    dependencies = [
        ("data_requests", "0001_initial"),
        # Canonical Partner + DataSharingAgreement + GeographicUnit must
        # exist before we lift rows.
        ("partners", "0004_partnerusagedaily"),
        ("reference_data", "0004_seed_partner_choice_lists"),
    ]

    operations = [
        migrations.RunPython(_lift, migrations.RunPython.noop),
    ]
