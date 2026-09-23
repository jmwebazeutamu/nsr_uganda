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

So the ladder is derived here, from ``GeographicUnit.Level`` — the UBOS
frame itself — and the column name for a level is derived from the level
(``county`` -> ``county_code``) rather than listed. A level that is
missing from a matview is now a fact this module can state, and callers
refuse instead of falling open.

**Not** derived from ``ScopeLevel``. The first version of this module
was, and county vanished from the ladder on production the moment it
deployed, because ``ScopeLevel`` had no ``COUNTY`` member at the time.
The fail-closed branch caught it — a county request was refused rather
than answered nationally — but the rung was still gone.
``ScopeLevel.COUNTY`` has since landed, which makes the two agree
again; the derivation stays pointed at ``GeographicUnit`` because that
is where the frame lives, and agreeing today is not the same as being
the source.
"""

from __future__ import annotations

from apps.reference_data.models import GeographicUnit

# NATIONAL is not a UBOS unit — there is no GeographicUnit row for "the
# country". It is the synthetic root of the ladder and the one level
# that means "do not filter".
NATIONAL = "national"

# The ladder, coarse to fine, straight off GeographicUnit.Level.
#
# Derived from the UBOS frame and NOT from ScopeLevel, which is an ABAC
# concept that mirrors the frame and adds national + partner. Deriving
# from the mirror once dropped county out of this ladder entirely — see
# the module docstring for what a missing rung costs.
LADDER: tuple[str, ...] = (
    NATIONAL,
    *(level.value for level in GeographicUnit.Level),
)

# Rank: coarser → smaller. national = 0 … village = 7.
LEVEL_RANK: dict[str, int] = {name: i for i, name in enumerate(LADDER)}

# The matview column that carries each level's code. Derived, not
# listed — a new level in ScopeLevel gets its column name for free, and
# no copy of this can drift.
LEVEL_COLUMN: dict[str, str] = {
    name: f"{name}_code" for name in LADDER if name != NATIONAL
}

# Spellings a caller may send. One copy.
ALIASES: dict[str, str] = {
    "country": NATIONAL,
    "subregion": GeographicUnit.Level.SUB_REGION.value,
    "sub-region": GeographicUnit.Level.SUB_REGION.value,
    "subcounty": GeographicUnit.Level.SUB_COUNTY.value,
    "sub-county": GeographicUnit.Level.SUB_COUNTY.value,
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
    levels = {NATIONAL}
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
        return {NATIONAL}
    return {name for name, rank in LEVEL_RANK.items() if rank <= limit}
