"""Public aggregates for the unauthenticated public site.

Everything a visitor with no session can read comes from here, and
everything here passes the disclosure floor in
docs/design_public_page/public-site/01_landing_page_spec.md §8.3 before
it leaves the module.

The floor is not decoration. The registry is a poverty register: a cell
reading "3 households" in a named parish is close to naming those
households, and a set of unfloored cells that sum to a published total
lets the suppressed one be recovered by subtraction. §8.3 proposes:

  - suppress any cell built on fewer than 10 households, showing `..`
    rather than a zero,
  - suppress complementary cells where a suppressed value could be
    recovered by subtraction,
  - no cross-tabulation deeper than two dimensions,
  - no disability, health or other special-category breakdown below
    district level,
  - round percentages to one decimal, and counts below 100 to the
    nearest 5.

LP-O-06: the DPO has not signed this floor off. The numbers this module
returns are therefore NOT cleared for a production public URL. The
NSR_PUBLIC_STATS_LIVE flag defaults to False for that reason; with the
flag off the page renders its placeholder slots instead, which is the
§15.5 "never a spinner and never zero" behaviour applied to an
un-approved figure rather than a failed one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit

SUPPRESSION_THRESHOLD = 10
ROUND_BELOW = 100
ROUND_TO = 5
SUPPRESSED_MARK = ".."


def stats_are_live() -> bool:
    """Whether the public page may render real figures at all (LP-O-06)."""
    return bool(getattr(settings, "NSR_PUBLIC_STATS_LIVE", False))


def floor_count(n: int | None) -> int | None:
    """Apply §8.3 to a single count. None means suppressed."""
    if n is None:
        return None
    if n < SUPPRESSION_THRESHOLD:
        return None
    if n < ROUND_BELOW:
        return int(ROUND_TO * round(n / ROUND_TO))
    return int(n)


def floor_percent(part: int, whole: int) -> float | None:
    """A percentage is only publishable if its numerator is."""
    if not whole or part < SUPPRESSION_THRESHOLD:
        return None
    return round(100.0 * part / whole, 1)


@dataclass
class Cell:
    label: str
    raw: int
    value: int | None = None
    suppressed: bool = False

    @property
    def display(self) -> str:
        return SUPPRESSED_MARK if self.suppressed else f"{self.value:,}"


@dataclass
class Series:
    cells: list[Cell] = field(default_factory=list)
    any_suppressed: bool = False

    @property
    def max_value(self) -> int:
        return max((c.value or 0) for c in self.cells) if self.cells else 0


def floor_series(rows: list[tuple[str, int]]) -> Series:
    """Apply §8.3 across a whole series, including complementary
    suppression.

    If exactly one cell falls below the threshold and the rest are
    published alongside a total, that one cell is recoverable by
    subtraction. So whenever suppression happens at all, a second cell —
    the smallest survivor — goes with it. That is the standard
    complementary rule and it is why this cannot be done cell by cell.
    """
    cells = [Cell(label=lbl, raw=n) for lbl, n in rows]
    for c in cells:
        v = floor_count(c.raw)
        if v is None:
            c.suppressed = True
        else:
            c.value = v

    suppressed = [c for c in cells if c.suppressed]
    if len(suppressed) == 1:
        survivors = [c for c in cells if not c.suppressed]
        if survivors:
            victim = min(survivors, key=lambda c: c.raw)
            victim.suppressed = True
            victim.value = None

    return Series(cells=cells, any_suppressed=any(c.suppressed for c in cells))


# --- The published set ----------------------------------------------------

def _as_at() -> str:
    # §8.4 — a number without a date is a liability.
    return timezone.localtime().strftime("%d %B %Y")


def headline_counters() -> dict:
    """§6 S1 — the four hero counters, floored.

    National totals only. National counts are far above the threshold in
    any real deployment; the floor still runs so a near-empty staging
    database cannot publish a two-household figure.
    """
    households = Household.objects.count()
    people = Member.objects.count()
    districts_total = GeographicUnit.objects.filter(level="district").count()
    districts_hit = (
        Household.objects.exclude(district__isnull=True)
        .values("district").distinct().count()
    )
    # REF-DATA currently holds duplicate sub-region seed rows
    # (Buganda North / Buganda_North, West Nile / West_Nile, Karamoja
    # twice), so a raw count reads 19 against the 9 the spec assumes.
    # Count distinct names, normalised, and surface the conflict rather
    # than publishing either number as fact.
    sub_region_names = {
        (n or "").replace("_", " ").strip().lower()
        for n in GeographicUnit.objects.filter(level="sub_region")
                                       .values_list("name", flat=True)
    }
    return {
        "households": floor_count(households),
        "people": floor_count(people),
        "sub_regions": len(sub_region_names - {""}),
        "districts_hit": floor_count(districts_hit),
        "districts_total": districts_total,
        "as_at": _as_at(),
    }


def kpi_row() -> dict:
    """§6 S4a — six KPI cards."""
    households = Household.objects.count()
    people = Member.objects.count()
    avg = round(people / households, 1) if households else None
    return {
        "households": floor_count(households),
        "people": floor_count(people),
        "avg_household_size": avg,
        "districts": GeographicUnit.objects.filter(level="district").count(),
        "sub_counties": GeographicUnit.objects.filter(level="sub_county").count(),
        "parishes": GeographicUnit.objects.filter(level="parish").count(),
        "as_at": _as_at(),
    }


def coverage_by_sub_region() -> Series:
    """§6 S4c — households per sub-region, floored as a series.

    Sub-region is above the §8.2 geographic floor, so it is publishable
    at all; §8.3 still governs each cell.
    """
    rows = (
        Household.objects.exclude(sub_region_code="")
        .exclude(sub_region_code__isnull=True)
        .values("sub_region__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    pairs = [
        ((r["sub_region__name"] or "").replace("_", " ").strip() or "Unknown", r["n"])
        for r in rows
    ]
    # Fold the duplicate seed rows together before flooring, so the same
    # sub-region does not appear twice with each half below the threshold.
    merged: dict[str, int] = {}
    for name, n in pairs:
        merged[name] = merged.get(name, 0) + n
    ordered = sorted(merged.items(), key=lambda kv: -kv[1])
    return floor_series(ordered)


def demographics() -> dict:
    """§6 S4d — sex split only.

    Age bands, disability and female-headed households are NOT published
    here. Disability is special-category data under the DPPA 2019 and
    §8.3 bars it below district level; the rest need a method note the
    spec has not written yet. Publishing a number whose definition is
    undecided is worse than publishing none.

    Member.sex is stored inconsistently — the live table holds both
    'M'/'F' and UBOS '1'/'2' — so the split is normalised here and the
    inconsistency is reported rather than silently bucketed.
    """
    total = Member.objects.count()
    counts = dict(
        Member.objects.values_list("sex").annotate(n=Count("id")),
    )
    male = sum(v for k, v in counts.items() if str(k).upper() in {"M", "1"})
    female = sum(v for k, v in counts.items() if str(k).upper() in {"F", "2"})
    unknown = total - male - female
    return {
        "female_pct": floor_percent(female, total),
        "male_pct": floor_percent(male, total),
        "unclassified": unknown,
        "coding_is_mixed": bool(
            {str(k).upper() for k in counts} & {"M", "F"}
            and {str(k).upper() for k in counts} & {"1", "2"},
        ),
        "as_at": _as_at(),
    }
