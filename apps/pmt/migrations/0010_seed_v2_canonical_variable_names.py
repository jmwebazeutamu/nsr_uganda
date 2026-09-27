"""Seed PMT v2 as a DRAFT: v1's model with canonical variable names.

v1 names a variable for what the analyst meant (`head_edu_tertiary`,
`floor_tiles_terrazzo`). Nothing in the name says which questionnaire
field it scores, so the binding lived only in `feature.path` and could
only be checked by reading the JSON. v2 names a variable for the field
it scores, with a qualifier where several variables score one field:

    head_edu_tertiary        ->  highest_grade__tertiary
    floor_tiles_terrazzo     ->  floor_material__tiles_terrazzo

`apps.pmt.variable_catalogue.canonical_name` is the one place that
spelling is decided, and `field_for_name` reverses it, so the chain
`name -> canonical_field -> choice_list_ref -> ChoiceList -> ChoiceOption`
is readable straight off the model.

Variables with no questionnaire binding keep their names, because there
is no field to name them after: `member_count` and `dependency_ratio`
are computed by the engine, `share_children_under_15` and
`rooms_per_capita` are composed over collections, and the `owns_*`
variables filter on `asset_type`, an ORM column with no canonical
question (ADR-0041 reports that binding as missing rather than
inventing one).

Two operands are corrected, and this is the part to read twice
-------------------------------------------------------------
v1 asks `education_level` for `"4"` and `"8"`. That list spells its
codes zero-padded — `04` is P1 and `08` is P5 — so both match nothing.
`head_edu_completed_primary` and `head_edu_secondary` therefore score
zero for everyone and collapse onto `head_edu_tertiary`; all three fired
on exactly 215 of 374 dev households. Of 1,374 graded Education rows,
233 heads at P7 or S1-S6 score zero on all three education terms.

v2 uses `["10".."23"]` (P7 and above) and `["11".."23"]` (S1 and above).
That is a change to what the model computes, so **v2 is created DRAFT
and must go through AC-PMT-MODEL-VERSION dual approval by MGLSD before
it can score anything** (SAD open item O-03). v1 stays ACTIVE and
untouched; nothing about this migration changes a single score.

Leaving the codes as they are was not an option: ADR-0041's activation
gate refuses a model naming codes the questionnaire does not carry, so a
v2 carrying `"4"` could never be activated at all.
"""

from django.db import migrations

#: old v1 name -> (canonical field, qualifier). A field of "" means the
#: variable has no questionnaire binding and keeps its name.
RENAMES = {
    "head_is_female":             ("sex", "female"),
    "head_edu_completed_primary": ("highest_grade", "completed_primary"),
    "head_edu_secondary":         ("highest_grade", "secondary"),
    "head_edu_tertiary":          ("highest_grade", "tertiary"),
    "floor_tiles_terrazzo":       ("floor_material", "tiles_terrazzo"),
    "floor_cement_or_brick":      ("floor_material", "cement_or_brick"),
    "roof_metal_or_tile":         ("roof_material", "metal_or_tile"),
    "wall_uncovered_adobe":       ("wall_material", "uncovered_adobe"),
    "wall_stone_lime_cement":     ("wall_material", "stone_lime_cement"),
    "wall_other_finished":        ("wall_material", "other_finished"),
    "electricity_for_lighting":   ("lighting_energy", "electricity"),
    "lighting_kerosene":          ("lighting_energy", "kerosene"),
    "piped_water_to_premises":    ("drinking_water_source", "piped_to_premises"),
    "open_defecation":            ("toilet_facility", "open_defecation"),
    "is_renting":                 ("tenure", "renting"),
    "any_cellphone":              ("telephone_1", "any"),
    # No questionnaire binding — see the module docstring.
    "member_count":               ("", ""),
    "share_children_under_15":    ("", ""),
    "rooms_per_capita":           ("", ""),
    "owns_car_or_van":            ("", ""),
    "owns_television":            ("", ""),
    "owns_motorcycle":            ("", ""),
    "owns_refrigerator":          ("", ""),
    "owns_computer":              ("", ""),
    "owns_radio":                 ("", ""),
}

#: Operands corrected against `education_level`'s actual codes. See the
#: module docstring — this is a policy change awaiting MGLSD approval.
CORRECTED_OPERANDS = {
    "highest_grade__completed_primary": [
        "10", "11", "12", "13", "14", "15", "16",
        "17", "18", "19", "20", "21", "22", "23",
    ],
    "highest_grade__secondary": [
        "11", "12", "13", "14", "15", "16",
        "17", "18", "19", "20", "21", "22", "23",
    ],
}

V2_VERSION = 2


def _canonical_name(field, qualifier):
    """Inlined from apps.pmt.variable_catalogue.

    A migration must keep working when that module changes, so the rule
    is copied here deliberately rather than imported — the same reason
    migration 0010 of `grievance` inlines its historical constants.
    `test_v2_names_match_the_catalogue_rule` pins the two together.
    """
    field = (field or "").strip()
    qualifier = (qualifier or "").strip().strip("_")
    return f"{field}__{qualifier}" if qualifier else field


def seed_v2(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")

    if PMTModelVersion.objects.filter(version=V2_VERSION).exists():
        return
    v1 = PMTModelVersion.objects.filter(version=1).first()
    if v1 is None:
        # Nothing to derive from. A fresh database gets v2 when it gets
        # v1; failing here would block the whole migration chain.
        return

    variables = []
    for entry in (v1.variables or []):
        entry = dict(entry)
        old = entry.get("name") or ""
        field, qualifier = RENAMES.get(old, ("", ""))
        new = _canonical_name(field, qualifier) if field else old
        entry["name"] = new

        feature = entry.get("feature")
        if isinstance(feature, dict) and new in CORRECTED_OPERANDS:
            feature = dict(feature)
            feature["operand"] = list(CORRECTED_OPERANDS[new])
            entry["feature"] = feature
            entry["comment"] = (
                (entry.get("comment") or "").rstrip(". ")
                + ". Operand corrected against education_level's padded codes "
                  "(migration pmt.0010); awaiting MGLSD approval."
            ).lstrip(". ")
        variables.append(entry)

    PMTModelVersion.objects.create(
        version=V2_VERSION,
        description=(
            "v1 with canonical variable names: a variable is named for the "
            "questionnaire field it scores. Two education operands corrected "
            "against education_level's zero-padded codes — see migration "
            "pmt.0010 and ADR-0041. DRAFT: requires MGLSD dual approval."
        ),
        variables=variables,
        intercept=v1.intercept,
        band_cutoffs=v1.band_cutoffs,
        band_strategy=v1.band_strategy,
        validation_r_squared=v1.validation_r_squared,
        status="draft",
        author="migration:pmt.0010",
    )


def drop_v2(apps, schema_editor):
    PMTModelVersion = apps.get_model("pmt", "PMTModelVersion")
    # Only while still a draft. If someone approved it, removing it is
    # not a migration's decision.
    PMTModelVersion.objects.filter(version=V2_VERSION, status="draft").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pmt", "0009_alter_pmtmodelversion_status"),
    ]

    operations = [
        migrations.RunPython(seed_v2, drop_v2),
    ]
