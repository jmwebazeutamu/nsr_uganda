"""WFP SCOPE connector mapping.

Third partner-MIS connector after PDM (S3-005) and NUSAF (S4-002).
WFP SCOPE is the World Food Programme's beneficiary registry; the
existing UN MoU with MGLSD allows household-level cross-referencing
for refugee + emergency-response cohorts.

SCOPE-specific quirks handled here:
- Beneficiary identifier is `scope_beneficiary_id` (UN-format like
  "UGA-2026-1234567").
- Geographic identifiers arrive as ISO-3166-2 region codes; SCOPE
  expects them under `admin1` / `admin2` / `admin3` keys (UN OCHA
  convention) rather than the NSR ladder. The mapper expects the
  caller to have already mapped admin levels to NSR codes — SCOPE
  upstream tooling does this via a static lookup table maintained by
  WFP. Bare codes pass through.
- Beneficiary state is one of `registered`, `active`, `inactive`.
  Only `active` rows promote to canonical members; the others are
  dropped (the connector emits an INFO note in canonical_payload's
  `_source_keys.dropped_inactive` count).
- Names can arrive in two languages — English (`name_en`) and a local
  script (`name_local`). The canonical schema doesn't have a local-
  language column today, so we preserve it in `_source_keys` for
  audit/lineage and use `name_en` for the canonical row.
- Phone numbers are pre-canonicalised E.164 by SCOPE; we pass through.
"""

from __future__ import annotations

_ACTIVE_STATES = frozenset({"active"})

_HEAD_ROLES = frozenset({
    "head", "household head", "hh head", "hoh", "head of household",
    "principal applicant", "primary registrant",
})


def wfp_scope_to_canonical(raw: dict) -> dict:
    """Convert a WFP SCOPE raw payload to the canonical NSR shape.

    Raises KeyError if the geographic block is missing. Inactive
    members are silently dropped from the roster; the dropped count
    is recorded in `_source_keys.dropped_inactive` for audit lineage.
    """
    geo = raw["geographic"]
    members_raw = raw.get("members", []) or []

    dropped_inactive = 0
    canonical_members: list[dict] = []
    line_number = 0
    for m in members_raw:
        state = (m.get("state") or "").strip().lower()
        if state and state not in _ACTIVE_STATES:
            dropped_inactive += 1
            continue
        line_number += 1
        canonical_members.append(_scope_member_to_canonical(m, line_number))

    canonical: dict = {
        "geographic": {
            "region": geo["region"],
            "sub_region": geo["sub_region"],
            "district": geo["district"],
            "county": geo["county"],
            "sub_county": geo["sub_county"],
            "parish": geo["parish"],
            "village": geo["village"],
        },
        "urban_rural": raw.get("urban_rural", "rural"),
        "address_narrative": raw.get("address_narrative", ""),
        "gps_lat": raw.get("gps_lat"),
        "gps_lng": raw.get("gps_lng"),
        "gps_accuracy_m": raw.get("gps_accuracy_m"),
        "members": canonical_members,
        "_source_keys": {
            "scope_beneficiary_id": raw.get("scope_beneficiary_id", ""),
            "cohort_code": raw.get("cohort_code", ""),
            "dropped_inactive": dropped_inactive,
        },
    }
    return canonical


def _scope_member_to_canonical(m: dict, line_number: int) -> dict:
    role = (m.get("role") or "").strip().lower()
    is_head = role in _HEAD_ROLES
    nin = (m.get("nin") or "").strip().upper()
    # Prefer English; preserve local-language name on the row for
    # lineage even though the canonical schema doesn't carry it
    # forward to Member yet.
    surname = m.get("surname") or m.get("name_en", "").split(" ", 1)[-1] or ""
    first_name = (
        m.get("first_name")
        or m.get("name_en", "").split(" ", 1)[0]
        or ""
    )
    out = {
        "line_number": m.get("line_number", line_number),
        "is_head": is_head,
        "surname": surname,
        "first_name": first_name,
        "other_name": m.get("other_name", ""),
        "sex": m.get("sex", ""),
        "date_of_birth": m.get("date_of_birth"),
        "age_years": m.get("age_years"),
        "relationship_to_head": (
            "" if is_head else (m.get("role") or m.get("relationship_to_head", ""))
        ),
        "telephone_1": m.get("telephone_1", ""),
        "telephone_2": m.get("telephone_2", ""),
        "nin": nin,
    }
    if m.get("name_local"):
        out["_local_name"] = m["name_local"]
    return out
