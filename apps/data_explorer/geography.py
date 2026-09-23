"""The geographic ladder, once.

Before this module the UBOS hierarchy was written out in six places:

  * ``GeographicUnit.Level`` — the UBOS frame itself (7 levels).
  * ``ScopeLevel`` — the same 7, plus national and partner.
  * ``validators._GEO_LEVELS`` — a rank dict, hand-numbered.
  * ``validators._GEO_ALIASES`` — the request spellings.
  * ``query_builder``'s own inline copy of those same aliases.
  * ``query_builder.field_map`` — **three** of the seven levels.

The last one was not a shorthand, it was a hole. ``field_map`` carried
sub_region, district and sub_county. A request scoped to a **county** —
a level ``ScopeLevel`` declares, ``Household`` carries as an FK, and the
validator happily accepts because it sits above the sub-county floor —
found no column, fell through the ``column is None`` branch, and
returned the queryset **unfiltered**. On production that read:

    county   102.2          -> 322 rows, 354 households   (the whole country)
    region   R-CENTRAL      -> 322 rows, 354 households
    county   TOTAL-NONSENSE -> 322 rows, 354 households

Not an empty answer — a national answer, labelled as one county, with
the k-anonymity suppression computed against the national population
rather than the county's. A nonsense code returned it too.

So the ladder is derived here, from ``ScopeLevel``, and the column name
for a level is derived from the level (``county`` -> ``county_code``)
rather than listed. A level that is missing from a matview is now a fact
this module can state, and callers refuse instead of falling open.
"""

from __future__ import annotations

from apps.security.models import ScopeLevel

# The ladder, coarse to fine, straight off ScopeLevel's declaration
# order. PARTNER is not geographic.
LADDER: tuple[str, ...] = tuple(
    level.value for level in ScopeLevel if level != ScopeLevel.PARTNER
)

# Rank: coarser → smaller. national = 0 … village = 7.
LEVEL_RANK: dict[str, int] = {name: i for i, name in enumerate(LADDER)}

# The matview column that carries each level's code. Derived, not
# listed — a new level in ScopeLevel gets its column name for free, and
# no copy of this can drift.
LEVEL_COLUMN: dict[str, str] = {
    name: f"{name}_code" for name in LADDER if name != ScopeLevel.NATIONAL
}

# Spellings a caller may send. One copy.
ALIASES: dict[str, str] = {
    "country": ScopeLevel.NATIONAL.value,
    "subregion": ScopeLevel.SUB_REGION.value,
    "sub-county": ScopeLevel.SUB_COUNTY.value,
    "subcounty": ScopeLevel.SUB_COUNTY.value,
    "sub-region": ScopeLevel.SUB_REGION.value,
}


def normalise_level(raw: str | None) -> str:
    """Lower-case and de-alias a requested level. '' for nothing."""
    level = (raw or "").strip().lower()
    return ALIASES.get(level, level)


def is_known_level(level: str) -> bool:
    return level in LEVEL_RANK


def scopable_levels(matview_model) -> set[str]:
    """Levels this matview can actually be filtered by.

    ``national`` is always scopable — it means "do not filter". Every
    other level needs its column physically on the matview.
    """
    levels = {ScopeLevel.NATIONAL.value}
    for level, column in LEVEL_COLUMN.items():
        if hasattr(matview_model, column):
            levels.add(level)
    return levels


def levels_down_to(floor: str) -> set[str]:
    """Every level from national down to and including ``floor``.

    This is the set a dataset claims to serve: its ``geographic_floor``
    is the finest grain it will answer at, so everything coarser is in
    scope by definition.
    """
    limit = LEVEL_RANK.get(floor)
    if limit is None:
        return {ScopeLevel.NATIONAL.value}
    return {name for name, rank in LEVEL_RANK.items() if rank <= limit}
