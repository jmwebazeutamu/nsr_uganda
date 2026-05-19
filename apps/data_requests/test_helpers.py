"""Test helpers — build canonical Partner + DSA via legacy-shape kwargs.

After ADR-0013 / US-S24-003 the canonical Partner and DSA live in
apps.partners. The DRS test suite was written against the older
DRS-local shape (allowed_scopes JSON, valid_from / valid_to,
contact_email). Rather than rewriting every fixture inline,
these helpers translate the legacy kwargs to the canonical shape.

`make_partner(code=..., name=..., contact_email=...)` returns an
apps.partners.Partner. `make_dsa(partner, reference, allowed_scopes,
valid_from, valid_to, status, ...)` returns an
apps.partners.DataSharingAgreement with the allowed_scopes JSON
unpacked into field_scope / geographic_scope M2M / monthly_row_budget /
entities_scope.programmes_allowed per the ADR-0013 mapping table.
"""

from __future__ import annotations

from datetime import date


def make_partner(*, code: str, name: str | None = None,
                 status: str = "active", contact_email: str = ""):
    from apps.partners.models import Partner
    return Partner.objects.create(
        code=code,
        name=name or code,
        type="agency",
        status=status,
        tone="neutral",
        primary_email=contact_email,
    )


def make_dsa(*, partner, reference: str, allowed_scopes: dict | None = None,
             status: str = "active",
             valid_from: date | None = None,
             valid_to: date | None = None,
             purpose: str = "",
             signed_by: str = "",
             signed_at=None):
    from apps.partners.models import DataSharingAgreement
    from apps.reference_data.models import GeographicUnit

    scopes = allowed_scopes or {}

    # Field group derivation: legacy 'household.id', 'member.name' → group keys.
    field_scope: dict[str, bool] = {}
    for f in scopes.get("fields") or []:
        group, _, _ = (f or "").partition(".")
        if group:
            field_scope[group] = True

    dsa = DataSharingAgreement.objects.create(
        partner=partner,
        reference=reference,
        version=1,
        status=status,
        effective_from=valid_from or date(2026, 1, 1),
        effective_to=valid_to or date(2030, 12, 31),
        monthly_row_budget=scopes.get("max_rows_per_request"),
        field_scope=field_scope,
        entities_scope={
            "programmes_allowed": scopes.get("programme_codes") or [],
        },
        sensitive_data_handling="none",
        retention_days=180,
        breach_sla_hours=72,
        signed_at=signed_at,
    )

    sub_region_codes = scopes.get("sub_region_codes") or []
    if sub_region_codes:
        existing = list(
            GeographicUnit.objects
            .filter(level="sub_region", code__in=sub_region_codes),
        )
        existing_codes = {g.code for g in existing}
        for code in sub_region_codes:
            if code not in existing_codes:
                existing.append(GeographicUnit.objects.create(
                    level="sub_region", code=code, name=code,
                    effective_from=date(2026, 1, 1),
                ))
        if existing:
            dsa.geographic_scope.add(*existing)

    return dsa
