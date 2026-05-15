"""DRS builder-schema generation.

Returns the full catalogue of fields, filter operators, and delivery
methods the DRS query builder needs to render — same structure for
every role, with `disabled` + `disabled_reason` flagged per-field
based on the user's active DSA (for partner roles) or never (for
operator roles).

This module is the source of truth the React DRS wizard reads from
(/api/v1/drs/builder-schema/). Both the operator-side DRSScreen and
the partner-side PartnerDRSScreen consume the same response —
client-side rendering of the disabled state is uniform; only the
flag values differ by role.

Contract guarantee (enforced by contract test): the top-level shape
{fields, filter_operators, delivery_methods} is invariant across
all roles. A new role that needs fewer fields gets `disabled: true`
entries, never an entirely missing key.
"""

from __future__ import annotations

from typing import Any

from .models import DataSharingAgreement, DsaStatus

# All known fields the registry exposes through DRS. Order matters
# for display; group separates them in the UI's field-selector.
FIELD_CATALOGUE: list[dict[str, Any]] = [
    # group, key, sensitivity per SAD §8.1
    {"group": "Identifiers", "key": "household.id",                    "sensitivity": "Public"},
    {"group": "Identifiers", "key": "household.sub_region_code",       "sensitivity": "Public"},
    {"group": "Geography",   "key": "household.urban_rural",           "sensitivity": "Public"},
    {"group": "Geography",   "key": "household.gps_lat",               "sensitivity": "Sensitive"},
    {"group": "Geography",   "key": "household.gps_lng",               "sensitivity": "Sensitive"},
    {"group": "Household",   "key": "household.current_vulnerability_band", "sensitivity": "Internal"},
    {"group": "Household",   "key": "household.current_pmt_score",     "sensitivity": "Internal"},
    {"group": "Identity",    "key": "member.id",                       "sensitivity": "Public"},
    {"group": "Identity",    "key": "member.line_number",              "sensitivity": "Public"},
    {"group": "Identity",    "key": "member.surname",                  "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.first_name",               "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.other_name",               "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.sex",                      "sensitivity": "Public"},
    {"group": "Identity",    "key": "member.date_of_birth",            "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.relationship_to_head",     "sensitivity": "Public"},
    {"group": "Identity",    "key": "member.telephone_1",              "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.telephone_2",              "sensitivity": "Personal"},
    {"group": "Identity",    "key": "member.nin_hash",                 "sensitivity": "Sensitive"},
    {"group": "Identity",    "key": "member.nin_last4",                "sensitivity": "Sensitive"},
]

# Filter operators a partner / operator can use to constrain rows.
# Same for every role; the values they can compare against depend
# on the field type and the DSA's per-field sensitivity.
FILTER_OPERATORS: list[dict[str, str]] = [
    {"op": "eq",          "label": "is",                "applies_to": "any"},
    {"op": "neq",         "label": "is not",            "applies_to": "any"},
    {"op": "in",          "label": "is one of",         "applies_to": "any"},
    {"op": "not_in",      "label": "is not one of",     "applies_to": "any"},
    {"op": "between",     "label": "between",           "applies_to": "numeric_or_date"},
    {"op": "starts_with", "label": "starts with",       "applies_to": "string"},
    {"op": "is_null",     "label": "is missing",        "applies_to": "any"},
]

# Delivery channels — partner-facing differ from operator-facing.
DELIVERY_METHODS: list[dict[str, Any]] = [
    {"id": "portal_download",
     "label": "Download from this portal (NDJSON, signed manifest)",
     "available_to": ["partner-analyst", "partner-dpo", "nsr-unit", "cdo"]},
    {"id": "sftp_push",
     "label": "SFTP push to your endpoint",
     "available_to": ["partner-analyst", "nsr-unit"]},
    {"id": "webhook",
     "label": "HTTPS webhook (HMAC-signed payload)",
     "available_to": ["partner-analyst", "nsr-unit"]},
]


def _active_partner_dsa(user) -> DataSharingAgreement | None:
    """Resolve the partner user's currently active DSA. Returns None
    when the user has no PARTNER scope (operator roles), or no active
    DSA under their partner code. The 'first active' is acceptable
    in MVP — partners with multiple active DSAs see fields the most
    permissive grants; tightening to per-DSA-selection lands later.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    from apps.security.models import OperatorScope, ScopeLevel
    partner_codes = list(
        OperatorScope.objects.filter(
            user=user, active=True, scope_level=ScopeLevel.PARTNER,
        ).exclude(scope_code="").values_list("scope_code", flat=True),
    )
    if not partner_codes:
        return None
    return (
        DataSharingAgreement.objects.filter(
            partner__code__in=partner_codes, status=DsaStatus.ACTIVE,
        ).order_by("-valid_from").first()
    )


def build_schema(user) -> dict[str, Any]:
    """Generate the builder schema for `user`. Same top-level shape
    for every role; partner roles get DSA-restricted fields flagged
    with disabled=True + a human-readable reason.

    Operators (NSR Unit, CDO, etc.) are NOT subjected to DSA
    field-level limits at this layer — their access is controlled
    by ABAC on the underlying viewsets and the audit chain. The
    builder schema gives them the full field catalogue.
    """
    is_partner = _active_partner_dsa(user) is not None
    dsa = _active_partner_dsa(user) if is_partner else None
    allowed_fields = (
        set((dsa.allowed_scopes or {}).get("fields", []))
        if is_partner else None
    )

    fields = []
    for entry in FIELD_CATALOGUE:
        # Copy so we don't mutate the module-level catalogue.
        item = dict(entry)
        if is_partner and allowed_fields is not None and entry["key"] not in allowed_fields:
            item["disabled"] = True
            item["disabled_reason"] = (
                f"Outside DSA {dsa.reference} clause 4.2.b — "
                "request expansion via your data steward."
            )
        else:
            item["disabled"] = False
            item["disabled_reason"] = ""
        fields.append(item)

    role = "partner" if is_partner else "operator"
    delivery_methods = [
        m for m in DELIVERY_METHODS
        if (role == "partner" and "partner-analyst" in m["available_to"])
            or (role == "operator" and "nsr-unit" in m["available_to"])
    ]

    return {
        "role": role,
        "dsa_reference": dsa.reference if dsa else "",
        "fields": fields,
        "filter_operators": list(FILTER_OPERATORS),
        "delivery_methods": delivery_methods,
    }
