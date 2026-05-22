"""US-S22-DE-09 / US-180 (PMT v1 ACTIVE seed).

Activates the canonical PMT v1 calibrated against UNHS 2023/24
(R² = 0.551, n = 15,682). Resolves open item O-03.

The variable list and weights are NOT hardcoded in engine code per
ADR-0025; they live as a JSON document on this row and are evaluated
by `apps.pmt.feature_evaluator`. Adding / removing variables in the
future is a Rule Editor + dual-approval workflow, not a deploy.

Forward: insert v1 with status='active'. Forward-only past Sprint 5
per ADR-0003; the reverse path is a noop (delete the row by
version=1 if you need to roll back, manually).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import migrations

V1_VARIABLES = [
    {
        "name": "member_count", "weight": -0.077,
        "feature": {"type": "direct", "path": "member_count"},
        "comment": "Household size — negative on log-consumption (larger HHs poorer per capita).",
    },
    {
        "name": "share_children_under_15", "weight": -0.117,
        "feature": {
            "type": "share_where", "collection": "members",
            "filter": {"age_years__lt": 15}, "default": 0,
        },
    },
    {
        "name": "head_is_female", "weight": +0.038,
        "feature": {
            "type": "equality",
            "path": "head_member.sex", "operand": "2",
        },
    },
    {
        "name": "head_edu_completed_primary", "weight": +0.099,
        "feature": {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["4", "8", "17", "18", "19", "20", "21", "22", "23"],
        },
        "comment": "Cumulative: any highest grade above P7.",
    },
    {
        "name": "head_edu_secondary", "weight": +0.154,
        "feature": {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["8", "17", "18", "19", "20", "21", "22", "23"],
        },
        "comment": "Cumulative: S1 or above.",
    },
    {
        "name": "head_edu_tertiary", "weight": +0.312,
        "feature": {
            "type": "membership",
            "path": "head_member.education.highest_grade",
            "operand": ["17", "18", "19", "20", "21", "22", "23"],
        },
        "comment": "Cumulative: tertiary or above.",
    },
    {
        "name": "floor_tiles_terrazzo", "weight": +0.326,
        "feature": {
            "type": "membership",
            "path": "dwelling.floor_material",
            "operand": ["17", "19"],
        },
    },
    {
        "name": "floor_cement_or_brick", "weight": +0.130,
        "feature": {
            "type": "membership",
            "path": "dwelling.floor_material",
            "operand": ["11", "12", "14"],
        },
    },
    {
        "name": "roof_metal_or_tile", "weight": +0.138,
        "feature": {
            "type": "membership",
            "path": "dwelling.roof_material",
            "operand": ["11", "12"],
        },
    },
    {
        "name": "wall_uncovered_adobe", "weight": +0.052,
        "feature": {
            "type": "membership",
            "path": "dwelling.wall_material",
            "operand": ["15", "17"],
        },
    },
    {
        "name": "wall_stone_lime_cement", "weight": +0.099,
        "feature": {
            "type": "membership",
            "path": "dwelling.wall_material",
            "operand": ["11", "24"],
        },
    },
    {
        "name": "wall_other_finished", "weight": +0.050,
        "feature": {
            "type": "membership",
            "path": "dwelling.wall_material",
            "operand": ["12", "13", "14", "22"],
        },
    },
    {
        "name": "rooms_per_capita", "weight": +0.292,
        "feature": {
            "type": "ratio",
            "numerator": "dwelling.total_rooms",
            "denominator": "member_count",
            "default": 0,
        },
    },
    {
        "name": "electricity_for_lighting", "weight": +0.112,
        "feature": {
            "type": "equality",
            "path": "utilities.lighting_energy",
            "operand": "01",
        },
    },
    {
        "name": "piped_water_to_premises", "weight": +0.075,
        "feature": {
            "type": "membership",
            "path": "utilities.drinking_water_source",
            "operand": ["10", "11"],
        },
    },
    {
        "name": "lighting_kerosene", "weight": -0.034,
        "feature": {
            "type": "equality",
            "path": "utilities.lighting_energy",
            "operand": "09",
        },
    },
    {
        "name": "open_defecation", "weight": -0.128,
        "feature": {
            "type": "equality",
            "path": "utilities.toilet_facility",
            "operand": "17",
        },
    },
    {
        "name": "owns_car_or_van", "weight": +0.294,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type__in": ["car", "minibus", "bus", "truck"]},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "owns_television", "weight": +0.228,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type__in": ["tv", "television"]},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "owns_motorcycle", "weight": +0.213,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "motorcycle"},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "any_cellphone", "weight": +0.185,
        "feature": {
            "type": "aggregate_any",
            "collection": "members", "path": "telephone_1",
        },
    },
    {
        "name": "owns_refrigerator", "weight": +0.157,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "refrigerator"},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "owns_computer", "weight": +0.141,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "computer"},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "owns_radio", "weight": +0.107,
        "feature": {
            "type": "presence_in_collection",
            "collection": "assets",
            "filter": {"asset_type": "radio"},
            "field": "count", "operator": "gt", "operand": 0,
        },
    },
    {
        "name": "is_renting", "weight": +0.108,
        "feature": {
            "type": "inequality", "path": "dwelling.tenure",
            "operand": "11",
        },
        "comment": "Owner-occupied (code 11) = reference; everything else = renting.",
    },
]


def _seed(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    # Idempotent — re-running the migration shouldn't insert twice.
    if PMTModelVersion.objects.filter(version=1).exists():
        return
    PMTModelVersion.objects.create(
        version=1,
        status="active",
        author="system",
        approved_by="system",
        description=(
            "NSR PMT v1 — UNHS 2023/24 calibration. National "
            "eligibility cutoff = 30th percentile (computed daily by "
            "PMTBandThresholdJob). 25-variable model; ADR-0025 DSL."
        ),
        intercept=Decimal("13.973"),
        validation_r_squared=Decimal("0.551"),
        calibration_dataset="UNHS 2023/24",
        calibration_year_end=2024,
        band_strategy="percentile",
        band_cutoffs={
            # Percentile ranks per spec §4.5: extreme 10% / poverty
            # 20% / vulnerable 30% / rest. The actual score thresholds
            # land in PMTBandThreshold via the daily beat job.
            "extreme_poverty": 10,
            "poverty":         20,
            "vulnerable":      30,
            "not_poor":        100,
        },
        variables=V1_VARIABLES,
    )


def _unseed(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    PMTModelVersion.objects.filter(version=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pmt", "0005_pmtmodelversion_calibration_fields"),
    ]

    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
