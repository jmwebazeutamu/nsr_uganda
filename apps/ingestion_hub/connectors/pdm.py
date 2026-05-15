"""PDM (Parish Development Model) connector mapping.

The PDM MIS at MGLSD exports households enrolled in the Parish
Development Model SACCO programme. Their export shape carries
programme-specific fields (sacco_code, tranche_history) that are
discarded for registry purposes, plus a roster that needs minor
normalisation to fit the canonical NSR payload (apps.ingestion_hub.
services.stage_from_landing / promote_stage_record).

The mapper is a pure function — no DB, no I/O — so it's trivially
unit-testable and re-runnable on archived raw payloads when the
canonical schema evolves.

PDM-specific quirks handled here:
- Geographic ladder arrives as names ("ADEKNINO sub-county") not as
  REF-DATA codes; we expect upstream to have resolved to codes already
  (the connector config holds the lookup). The mapper just passes
  through whatever geographic codes the raw payload supplies.
- Roster member field 'role' carries "Household Head", "Spouse", etc.
  We normalise the head sentinel to canonical `is_head: True` and copy
  the rest to `relationship_to_head`.
- NIN is uppercase in PDM; we strip + uppercase for the NIN trio.
- Phone numbers are pre-normalised by the upstream side; we don't try
  to re-canonicalise here.
"""

from __future__ import annotations


def pdm_to_canonical(raw: dict) -> dict:
    """Convert a PDM raw payload to the canonical NSR shape.

    Raises KeyError if required keys are missing — the caller (the
    connector run) catches and routes the row to Quarantine.
    """
    geo = raw["geographic"]  # KeyError → caller quarantines
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
        "members": [_pdm_member_to_canonical(m, i)
                    for i, m in enumerate(raw.get("members", []) or [], start=1)],
        # PDM-specific lineage so the audit chain can trace back.
        "_source_keys": {
            "pdm_household_id": raw.get("pdm_household_id", ""),
            "sacco_code": raw.get("sacco_code", ""),
        },
    }
    return canonical


def _pdm_member_to_canonical(m: dict, line_number: int) -> dict:
    role = (m.get("role") or "").strip().lower()
    is_head = role in {"head", "household head", "hh head"}
    nin = (m.get("nin") or "").strip().upper()
    return {
        "line_number": m.get("line_number", line_number),
        "is_head": is_head,
        "surname": m.get("surname", ""),
        "first_name": m.get("first_name", ""),
        "other_name": m.get("other_name", ""),
        "sex": m.get("sex", ""),
        "date_of_birth": m.get("date_of_birth"),
        "age_years": m.get("age_years"),
        "relationship_to_head": (
            "" if is_head else (m.get("role") or m.get("relationship_to_head", ""))
        ),
        "telephone_1": m.get("telephone_1") or m.get("phone", ""),
        "telephone_2": m.get("telephone_2", ""),
        "nin": nin,
    }
