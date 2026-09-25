"""Canonical DSA-to-programme geography contract.

Programmes never maintain a second geographic policy.  Their saved units are
validated against ``DataSharingAgreement.geographic_scope`` (the UBOS-unit
M2M) and may inherit that exact scope when a geographically limited DSA is
used without an explicit programme selection.
"""

from __future__ import annotations

from apps.reference_data.models import GeographicUnit


class ProgrammeGeographyScopeError(ValueError):
    """A programme geography conflicts with its governing DSA."""


def _is_same_or_descendant(unit: GeographicUnit, ancestor_ids: set[str]) -> bool:
    """Whether ``unit`` is directly in, or descends from, a DSA unit."""
    current = unit
    while current is not None:
        if str(current.id) in ancestor_ids:
            return True
        current = current.parent
    return False


def programme_geography_contract(dsa) -> dict:
    """Server representation consumed by display, picker and validation.

    Empty DSA geography explicitly means national coverage.  Otherwise the
    units returned are the legal roots: a region root authorises its UBOS
    descendants, while preserving the region itself as the default inherited
    programme scope.
    """
    units = list(dsa.geographic_scope.order_by("level", "code"))
    return {
        "dsa_id": str(dsa.id),
        "dsa_reference": dsa.reference,
        "is_national": not units,
        "requires_programme_scope": bool(units),
        "units": [
            {"id": str(unit.id), "code": unit.code, "name": unit.name, "level": unit.level}
            for unit in units
        ],
    }


def validated_programme_geography(dsa, units) -> list[GeographicUnit]:
    """Return a legal programme scope, inheriting a limited DSA if needed."""
    if dsa is None:
        return list(units or [])
    if dsa.status != "active":
        raise ProgrammeGeographyScopeError(
            f"DSA {dsa.reference} is not active and cannot govern a programme."
        )
    roots = list(dsa.geographic_scope.all())
    selected = list(units or [])
    if not roots:
        return selected
    if not selected:
        # Explicit inherited values are persisted; this never produces an
        # empty/national programme under a geographically restricted DSA.
        return roots
    root_ids = {str(unit.id) for unit in roots}
    outside = [unit for unit in selected if not _is_same_or_descendant(unit, root_ids)]
    if outside:
        allowed = ", ".join(f"{unit.name} ({unit.level})" for unit in roots)
        requested = ", ".join(f"{unit.name} ({unit.level})" for unit in outside)
        raise ProgrammeGeographyScopeError(
            f"Programme geography {requested} is outside DSA {dsa.reference}. "
            f"Allowed DSA scope: {allowed}."
        )
    return selected
