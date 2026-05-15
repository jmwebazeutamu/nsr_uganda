"""Phone-number normalisation for DDUP tier 2 deterministic matching.

SAD §4.3.1: "Exact match on phone number normalised to E.164." The
Ugandan mobile regex (AC-PHONE-FORMAT, SAD §4.2.5) accepts
^(\\+?256|0)(7|2|3|4)\\d{8}$. We collapse all three accepted forms to
the canonical +256XXXXXXXXX so matching is a single equality check.
"""

from __future__ import annotations

import re

E164_UG = re.compile(r"^\+256[2347]\d{8}$")
_RAW_UG = re.compile(r"^(\+?256|0)([2347]\d{8})$")


def to_e164(raw: str | None) -> str | None:
    """Return the +256XXXXXXXXX canonical form, or None when the input
    cannot be coerced to a valid Ugandan mobile."""
    if not raw:
        return None
    cleaned = raw.strip().replace(" ", "").replace("-", "")
    if E164_UG.fullmatch(cleaned):
        return cleaned
    m = _RAW_UG.fullmatch(cleaned)
    if not m:
        return None
    return f"+256{m.group(2)}"
