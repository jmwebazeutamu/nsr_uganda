"""US-S22-DE-07 — seed a DRAFT PMTModelVersion listing the
detail-entity variable surface.

The current ACTIVE model (when one exists) stays untouched —
this is a draft awaiting dual-approval per AC-PMT-MODEL-VERSION.
Weights are all 0.0 placeholders so activation would be a no-op
until the real calibration coefficients land (open item O-03).

The variable set mirrors apps.pmt.engine._household_features so
every variable resolves to a non-None raw value on a fully-
populated household (AC-DE-PMT-VARIABLES-RESOLVE).

Forward-only per CLAUDE.md (past Sprint 5). Reverse path deletes
the DRAFT row by version number.
"""

from __future__ import annotations

from django.db import migrations

# Pinning version=22001 (i.e. US-S22-DE-01) keeps it distinct from any
# real production model version while staying a recognisable handle
# in audit logs. Real calibrated models land at version=1, 2, … by
# the operator-facing draft → pending → active workflow.
_DRAFT_VERSION = 22001

_VARIABLES = [
    {"variable": "household.dwelling.floor_material",          "weight": 0.0, "transform": "identity"},
    {"variable": "household.dwelling.roof_material",           "weight": 0.0, "transform": "identity"},
    {"variable": "household.dwelling.wall_material",           "weight": 0.0, "transform": "identity"},
    {"variable": "household.utilities.drinking_water_source",  "weight": 0.0, "transform": "identity"},
    {"variable": "household.utilities.toilet_facility",        "weight": 0.0, "transform": "identity"},
    {"variable": "household.utilities.cooking_fuel",           "weight": 0.0, "transform": "identity"},
    {"variable": "household.utilities.lighting_energy",        "weight": 0.0, "transform": "identity"},
    {"variable": "household.livelihood.land_hectares",         "weight": 0.0, "transform": "log1p"},
    {"variable": "household.food_security.fies_raw_score",     "weight": 0.0, "transform": "identity"},
    {"variable": "household.food_consumption.fcs_score",       "weight": 0.0, "transform": "identity"},
    {"variable": "assets.radio.count",                         "weight": 0.0, "transform": "present_as_one"},
    {"variable": "assets.tv.count",                            "weight": 0.0, "transform": "present_as_one"},
    {"variable": "assets.motorcycle.count",                    "weight": 0.0, "transform": "present_as_one"},
    {"variable": "livestock.cattle.count",                     "weight": 0.0, "transform": "log1p"},
    {"variable": "disabled_member_count",                      "weight": 0.0, "transform": "identity"},
    {"variable": "chronic_ill_member_count",                   "weight": 0.0, "transform": "identity"},
    {"variable": "school_age_out_of_school_count",             "weight": 0.0, "transform": "identity"},
    {"variable": "household.head_member.education.highest_grade", "weight": 0.0, "transform": "identity"},
    {"variable": "household.head_member.employment.sector",    "weight": 0.0, "transform": "identity"},
    {"variable": "member_count",                               "weight": 0.0, "transform": "identity"},
    {"variable": "household.head_member.sex",                  "weight": 0.0, "transform": "identity"},
    {"variable": "dependency_ratio",                           "weight": 0.0, "transform": "identity"},
]

_BAND_CUTOFFS = {
    "extreme_poverty": 0,
    "poverty": 30,
    "vulnerable": 60,
    "not_poor": 80,
}


def _seed(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    PMTModelVersion.objects.get_or_create(
        version=_DRAFT_VERSION,
        defaults={
            "status": "draft",
            "description": (
                "US-S22-DE-07 detail-entity placeholder. Variable surface "
                "matches apps.pmt.engine._household_features. Weights are "
                "0.0 placeholders pending calibration (open item O-03)."
            ),
            "author": "system",
            "intercept": 0,
            "variables": _VARIABLES,
            "band_cutoffs": _BAND_CUTOFFS,
        },
    )


def _unseed(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    PMTModelVersion.objects.filter(version=_DRAFT_VERSION).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pmt", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
