"""Static map of ChoiceList → field paths where the codes are stored.

Source of truth for the Admin Console "Used by" column. Whenever a
ChoiceList is referenced from a model field, intake form field, or
DRS query selector, add the dotted path here. The Admin Console reads
this dict (not auto-introspection) so a code-list can be marked as
used even when the consumer hasn't been built yet.

Convention:
    list_name → ["module.entity.field", ...]

Modules use the operator-console vocabulary:
    intake.<entity>.<field>      — questionnaire-bound fields
    drs.<filter>                 — DRS query selector
    pmt.<feature>                — PMT DSL membership tests
    grm.<field>                  — grievance metadata
"""

from __future__ import annotations

CHOICELIST_USAGE: dict[str, list[str]] = {
    # Member / Household demographic fields (apps/data_management).
    "sex":                       ["intake.member.sex", "drs.member.sex"],
    "marital_status":            ["intake.member.marital_status"],
    "relationship":              ["intake.member.relationship_to_head"],
    "education_level":           ["intake.member.education_level", "drs.member.edu", "pmt.head_edu_*"],
    "disability_type":           ["intake.member.disability_type"],
    "religion":                  ["intake.member.religion"],

    # Dwelling (apps/data_management).
    "dwelling_type":             ["intake.dwelling.type"],
    "dwelling_tenure":           ["intake.dwelling.tenure", "pmt.is_renting"],
    "wall_material":             ["intake.dwelling.wall_material"],
    "roof_material":             ["intake.dwelling.roof_material"],
    "floor_material":            ["intake.dwelling.floor_material", "pmt.floor_tiles_terrazzo"],

    # Utilities.
    "water_source":              ["intake.utilities.water_source"],
    "lighting_source":           ["intake.utilities.lighting_source"],
    "cooking_fuel":              ["intake.utilities.cooking_fuel"],
    "toilet_type":               ["intake.utilities.toilet_type", "pmt.open_defecation"],

    # Assets.
    "asset_type":                ["intake.assets.asset_type", "pmt.owns_*"],

    # Employment.
    "employment_status":         ["intake.employment.status"],
    "income_source":             ["intake.employment.income_source"],

    # Programme / partner side.
    "programme_status":          ["partners.programme.status"],
    "programme_signoff_status":  ["partners.programme.signoff.status"],
    "partner_kind":              ["partners.partner.kind"],
    "beneficiary_enrolment_status": ["beneficiaries.enrolment.status"],
    "referral_status":           ["referral.referral.status"],

    # PMT trigger source.
    "pmt_trigger_source":        ["pmt.result.trigger_source"],
}


def field_paths_for(list_name: str) -> list[str]:
    """Public lookup. Returns [] when the list isn't registered yet."""
    return list(CHOICELIST_USAGE.get(list_name, []))


def usage_count(list_name: str) -> int:
    return len(CHOICELIST_USAGE.get(list_name, []))
