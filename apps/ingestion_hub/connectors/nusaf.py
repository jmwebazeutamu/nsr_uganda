"""NUSAF (Northern Uganda Social Action Fund) connector mapping.

NUSAF is the second partner-MIS connector after PDM (S3-005). Both
flow through DIH using the canonical NSR payload, so most of the
shape is identical; the differences are NUSAF-specific export quirks
that the mapper normalises:

- Beneficiary identifier is `nusaf_beneficiary_id`, no SACCO concept.
- Roster role vocab uses Luo administrative terms: 'Won Pacu' (head of
  homestead), 'Dako' (wife), 'Latin' (child); we accept the lower-cased
  English equivalents too so legacy exports keep working.
- Geographic identifiers arrive as 'sub_county_code', 'parish_code',
  'village_code' (suffixed) instead of bare 'sub_county'; the mapper
  strips the suffix into the canonical key.
- NIN is already uppercased upstream but we normalise defensively
  (matching the PDM mapper).
"""

from __future__ import annotations

_HEAD_ROLES = frozenset({
    "head", "household head", "hh head", "won pacu", "wonpacu",
})


def nusaf_to_canonical(raw: dict) -> dict:
    """Convert a NUSAF raw payload to the canonical NSR shape.

    Raises KeyError if required keys are missing — the caller (the
    connector run) catches and routes the row to Quarantine.
    """
    geo = raw["geographic"]
    canonical: dict = {
        "geographic": {
            "region": _strip_code_suffix(geo["region"]),
            "sub_region": _strip_code_suffix(geo["sub_region"]),
            "district": _strip_code_suffix(geo["district"]),
            "county": _strip_code_suffix(geo["county"]),
            "sub_county": _strip_code_suffix(geo["sub_county"]),
            "parish": _strip_code_suffix(geo["parish"]),
            "village": _strip_code_suffix(geo["village"]),
        },
        "urban_rural": raw.get("urban_rural", "rural"),
        "address_narrative": raw.get("address_narrative", ""),
        "gps_lat": raw.get("gps_lat"),
        "gps_lng": raw.get("gps_lng"),
        "gps_accuracy_m": raw.get("gps_accuracy_m"),
        "members": [_nusaf_member_to_canonical(m, i)
                    for i, m in enumerate(raw.get("members", []) or [], start=1)],
        "_source_keys": {
            "nusaf_beneficiary_id": raw.get("nusaf_beneficiary_id", ""),
            "project_code": raw.get("project_code", ""),
        },
    }
    return canonical


def _strip_code_suffix(value: dict | str) -> str:
    """NUSAF geo blocks sometimes nest {'code': 'X', 'name': '...'}.
    Accept either a bare string or that dict shape."""
    if isinstance(value, dict):
        return value.get("code", "") or ""
    return value or ""


def _nusaf_member_to_canonical(m: dict, line_number: int) -> dict:
    role = (m.get("role") or "").strip().lower()
    is_head = role in _HEAD_ROLES
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
        "telephone_1": m.get("telephone_1") or m.get("msisdn", ""),
        "telephone_2": m.get("telephone_2", ""),
        "nin": nin,
    }
