"""Resolving a geographic code when two sources spell it differently.

Uganda's county codes reach the registry in two spellings:

  * The **UBOS workbook** carries the county segment unpadded, and
    `scripts/load_ubos_geography.py` composes codes verbatim from it —
    ``320.2``, ``411.5``, ``414.1``.
  * The **Kobo form** sends ``a3_county_municipality`` zero-padded —
    ``320_02`` — which the connector turns into ``320.02``.

Nothing reconciled them. A staged record naming ``320.02`` found no
GeographicUnit, so `geo_backfill` fabricated one with ``name = code``
(its documented placeholder behaviour), and promotion attached the
household to the fabrication. The result was two rows for one real
county and households split between them: Kinkizi County held 3
households under ``414.01`` and 4 under ``414.1``, and no county-scoped
query ever saw all 7.

Only the county segment differs. Sub-county and parish segments are
two-digit zero-padded in **both** frames (``320.2.11.08`` vs
``320.02.11.08`` differ in one place only).

## Why this resolves rather than rewrites

The tempting fix is to strip the zero in the connector. It is wrong:
``412.02`` is a real, named, ACTIVE county row ("Nyakagyeme"), and
``412.2`` is a *different* real county ("Rujumbura County"). Stripping
would silently move households from one to the other.

So this does not transform a code — it looks for a row that exists,
trying the spelling it was given first and the alternative only if the
first finds nothing. A code that already resolves is never touched.
"""

from __future__ import annotations

from .models import GeographicUnit

# Which dotted segment carries the county. district.COUNTY.sub_county.parish
_COUNTY_SEGMENT = 1  # zero-based


def code_spellings(code: str) -> list[str]:
    """`code` first, then the same code with the county segment's
    zero-padding flipped. Order matters: the given spelling wins.

    Returns one entry for codes with no county segment (region,
    sub_region, district) or where flipping changes nothing.
    """
    if not code:
        return []
    parts = code.split(".")
    if len(parts) <= _COUNTY_SEGMENT:
        return [code]

    county = parts[_COUNTY_SEGMENT]
    if not county.isdigit():
        return [code]

    if county.startswith("0"):
        alternative = county.lstrip("0") or "0"
    else:
        alternative = f"0{county}"

    if alternative == county:
        return [code]

    alt_parts = list(parts)
    alt_parts[_COUNTY_SEGMENT] = alternative
    return [code, ".".join(alt_parts)]


def resolve_geographic_unit(level: str, code: str) -> GeographicUnit | None:
    """The GeographicUnit a (level, code) names, across both spellings.

    Prefers an exact match on the code as given. Falls back to the
    alternative county-segment spelling only when the exact code names
    nothing, so a code that resolves today keeps resolving to the same
    row. Returns None when neither spelling exists — the caller decides
    whether that is an error (promotion) or a row to create
    (geo_backfill).

    Latest `effective_from` wins, matching how promotion already picked
    among versioned rows.
    """
    for candidate in code_spellings(code):
        row = (
            GeographicUnit.objects
            .filter(level=level, code=candidate)
            .order_by("-effective_from")
            .first()
        )
        if row is not None:
            return row
    return None
