"""US-S20-006 — shared map of geographic questions → REF-DATA levels.

Used by both:
- apps.intake.admin (interactive preview schema endpoint, inlines
  options with parent_code for client-side cascade), and
- apps.intake.xlsform_export (writes proper choice_filter columns
  + a widened choices sheet so Kobo Enketo runs the cascade
  server-side at form runtime).

Keeping the mapping in one place so a future legacy-form import
that names the columns differently (e.g. a future questionnaire
v3) can declare its own list without divergent special-cases on
each side.
"""

from __future__ import annotations

# FormQuestion.name → (GeographicUnit.level, parent question name)
# Parent question is None for the top-level region select.
GEO_QUESTIONS: dict[str, tuple[str, str | None]] = {
    "a0_region":                ("region",     None),
    "a1_subregion":             ("sub_region", "a0_region"),
    "a2_district_city":         ("district",   "a1_subregion"),
    "a3_county_municipality":   ("county",     "a2_district_city"),
    "a4_subcounty_division_tc": ("sub_county", "a3_county_municipality"),
    "a5_parish_ward":           ("parish",     "a4_subcounty_division_tc"),
}

# All GeographicUnit levels we map onto, in cascade order from root
# to leaf. Used to build the choices sheet header columns.
GEO_LEVELS_ROOT_TO_LEAF = (
    "region", "sub_region", "district", "county", "sub_county", "parish",
)

# Parent column on the choices sheet for each child level. XLSForm's
# choice_filter expression references this column name.
GEO_PARENT_COLUMN: dict[str, str] = {
    "sub_region": "region",
    "district":   "sub_region",
    "county":     "district",
    "sub_county": "county",
    "parish":     "sub_county",
}


def geo_options_for(level: str) -> list[dict]:
    """Return [{code, label, parent_code}] for every active
    GeographicUnit at `level`, sorted by name. parent_code is the
    parent unit's `code` (empty for top-level)."""
    from apps.reference_data.models import GeographicUnit
    units = (
        GeographicUnit.objects.filter(level=level, status="active")
        .select_related("parent").order_by("name")
    )
    return [
        {
            "code": gu.code, "label": gu.name,
            "parent_code": gu.parent.code if gu.parent_id else "",
        }
        for gu in units
    ]


def choice_filter_for(question_name: str) -> str:
    """XLSForm choice_filter expression for a geo question, or "" for
    the top-level. Reads the parent column off the choices sheet —
    `region=${a0_region}` means "show options whose `region` cell
    equals the selected value of question a0_region"."""
    if question_name not in GEO_QUESTIONS:
        return ""
    level, parent_q = GEO_QUESTIONS[question_name]
    if not parent_q:
        return ""
    return f"{GEO_PARENT_COLUMN[level]}=${{{parent_q}}}"
