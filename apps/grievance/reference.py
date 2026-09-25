"""Grievance case numbers — GRM-2026-0001.

The scheme, the normalisation and the counter all live in
`apps.reference_data.references` now, shared with UPD, DRS and REF. This
module is what the grievance app calls, and it exists so that callers
keep saying `reference.assign(g)` rather than repeating the prefix at
every call site.

See ADR-0038 for why the numbers are sequential when CLAUDE.md
otherwise forbids that, and ADR-0039 for the other three modules.
"""

from __future__ import annotations

from apps.reference_data.references import (  # noqa: F401 — re-exported
    CONFUSABLES,
    GRIEVANCE as PREFIX,
    format_reference as _format,
    looks_like_a_reference as _looks,
    next_reference as _next,
    normalise as _normalise,
    year_of,
)


def format_reference(year: int, number: int) -> str:
    return _format(PREFIX, year, number)


def normalise(raw: str) -> str:
    return _normalise(raw, prefix=PREFIX)


def looks_like_a_reference(raw: str) -> bool:
    return _looks(raw, prefix=PREFIX)


def next_reference(year: int) -> str:
    return _next(PREFIX, year)


def assign(grievance) -> str:
    """Numbered in the year the case was OPENED, so one raised at 23:00
    on 31 December keeps a number from the year it happened."""
    from apps.reference_data.references import assign as _assign

    return _assign(grievance, PREFIX, date_field="opened_at")
