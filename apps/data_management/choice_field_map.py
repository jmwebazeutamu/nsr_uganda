"""Single source of truth for every coded field on Household,
HouseholdMember, and inside the source_payload questionnaire blob.

Per ADR-0010 §4 this is the ONLY place app code names a ChoiceList.
Adding a new coded field is a one-line edit here; the resolver,
serializer label fields, and detail-view rendering follow from it
without further wiring.

Three maps:

* `HOUSEHOLD_FIELDS` — coded columns on Household. Drives
  `get_<field>_label()` (attached via AppConfig.ready hook) and the
  `<field>_label` SerializerMethodField on HouseholdSerializer.

* `MEMBER_FIELDS` — same shape, for Member.

* `PAYLOAD_FIELDS` — paths into the source_payload JSON
  (StageRecord.canonical_payload). Path tuples use `"*"` as a
  wildcard for array indices (e.g. the per-member nested blocks).
  Drives the parallel `source_payload_labels` tree.

Value shape: `(list_name, kind)` where kind ∈ `"single"` | `"multi"`.
Multi-select fields store space-separated codes (XLSForm convention)
and resolve to `list[str]` labels.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal["single", "multi"]

# --- ORM fields -------------------------------------------------------------

HOUSEHOLD_FIELDS: dict[str, tuple[str, Kind]] = {
    "dwelling_tenure": ("tenure", "single"),
    "residence_status": ("residency_status", "single"),
    "urban_rural": ("rural_urban", "single"),
}

MEMBER_FIELDS: dict[str, tuple[str, Kind]] = {
    "sex": ("sex", "single"),
    "nin_status": ("nin_status", "single"),
    "relationship_to_head": ("relationship", "single"),
    "marital_status": ("marital_status", "single"),
    "nationality": ("nationality", "single"),
    "residency_status": ("residency_status", "single"),
    "birth_certificate_status": ("birth_certificate", "single"),
}


# --- US-S22-DE detail-entity coded fields ----------------------------------
#
# One map per detail entity. attach_label_methodfields() applies these to
# the matching ModelSerializer in apps/data_management/api.py.

DWELLING_FIELDS: dict[str, tuple[str, Kind]] = {
    "tenure": ("dwelling_tenure", "single"),
    "dwelling_type": ("dwelling_type", "single"),
    "roof_material": ("roof_material", "single"),
    "wall_material": ("wall_material", "single"),
    "floor_material": ("floor_material", "single"),
}

UTILITIES_FIELDS: dict[str, tuple[str, Kind]] = {
    "cooking_fuel": ("cooking_fuel", "single"),
    "lighting_energy": ("lighting_energy", "single"),
    "drinking_water_source": ("drinking_water_source", "single"),
    "toilet_facility": ("toilet_facility", "single"),
    "waste_disposal": ("waste_disposal", "single"),
}

LIVELIHOOD_FIELDS: dict[str, tuple[str, Kind]] = {
    "main_livelihood": ("main_livelihood", "single"),
    "agricultural_purpose": ("agricultural_purpose", "single"),
    "land_ownership": ("land_ownership", "single"),
    "land_title": ("land_title", "single"),
    "crop_production_zone": ("agricultural_zone", "single"),
    "livestock_zone": ("agricultural_zone", "single"),
}

# FIES: every column is yes/no-affirmative coded.
FOOD_SECURITY_FIELDS: dict[str, tuple[str, Kind]] = {
    "worried_food": ("yes_no", "single"),
    "unhealthy_food": ("yes_no", "single"),
    "limited_variety": ("yes_no", "single"),
    "skipped_meal": ("yes_no", "single"),
    "ate_less": ("yes_no", "single"),
    "ran_out_food": ("yes_no", "single"),
    "hungry_no_eat": ("yes_no", "single"),
    "whole_day_no_eat": ("yes_no", "single"),
}

FOOD_CONSUMPTION_FIELDS: dict[str, tuple[str, Kind]] = {
    "staples_source": ("food_source", "single"),
    "pulses_source": ("food_source", "single"),
    "dairy_source": ("food_source", "single"),
    "meat_source": ("food_source", "single"),
    "vegetables_source": ("food_source", "single"),
    "fruits_source": ("food_source", "single"),
    "oils_source": ("food_source", "single"),
    "sugar_source": ("food_source", "single"),
    "condiments_source": ("food_source", "single"),
}

ASSET_FIELDS: dict[str, tuple[str, Kind]] = {
    "asset_type": ("asset_type", "single"),
}

CROP_FIELDS: dict[str, tuple[str, Kind]] = {
    "crop_name": ("crop_name", "single"),
}

LIVESTOCK_FIELDS: dict[str, tuple[str, Kind]] = {
    "livestock_type": ("livestock_type", "single"),
}

SHOCK_FIELDS: dict[str, tuple[str, Kind]] = {
    "shock_type": ("shock_type", "single"),
    "severity": ("severity_level", "single"),
}

COPING_FIELDS: dict[str, tuple[str, Kind]] = {
    "strategy_type": ("coping_strategy_type", "single"),
    "frequency": ("coping_frequency", "single"),
}

HEALTH_FIELDS: dict[str, tuple[str, Kind]] = {
    "chronic_illness_flag": ("yes_no", "single"),
}

DISABILITY_FIELDS: dict[str, tuple[str, Kind]] = {
    "seeing": ("wg_difficulty_level", "single"),
    "hearing": ("wg_difficulty_level", "single"),
    "walking": ("wg_difficulty_level", "single"),
    "memory": ("wg_difficulty_level", "single"),
    "selfcare": ("wg_difficulty_level", "single"),
    "communication": ("wg_difficulty_level", "single"),
}

EDUCATION_FIELDS: dict[str, tuple[str, Kind]] = {
    "literacy_status": ("literacy_status", "single"),
    "ever_attended": ("yes_no", "single"),
    "never_attended_reason": ("never_attended_reason", "single"),
    "highest_grade": ("highest_grade", "single"),
    "currently_attending": ("yes_no", "single"),
    "why_stopped": ("why_stopped_school", "single"),
}

EMPLOYMENT_FIELDS: dict[str, tuple[str, Kind]] = {
    "main_activity_last_30d": ("employment_main_activity", "single"),
    "work_frequency": ("work_frequency", "single"),
    "sector": ("employment_sector", "single"),
    "employment_status": ("employment_status", "single"),
    "not_working_reason": ("not_working_reason", "single"),
    "is_govt_programme_beneficiary": ("yes_no", "single"),
    "currently_benefiting": ("yes_no", "single"),
    "made_savings": ("yes_no", "single"),
    "savings_location": ("savings_location", "single"),
}

# --- source_payload (StageRecord.canonical_payload) paths -------------------
#
# Path tuples are walked literally. Use "*" for an array index. The
# resolver visits every matching leaf and writes a parallel entry
# into source_payload_labels at the same path.

PAYLOAD_FIELDS: dict[tuple[str, ...], tuple[str, Kind]] = {
    # Housing & Assets tab
    ("housing", "tenure"): ("tenure", "single"),
    ("housing", "dwelling_type"): ("dwelling_type", "single"),
    ("housing", "roof_material"): ("roof_material", "single"),
    ("housing", "wall_material"): ("wall_material", "single"),
    ("housing", "floor_material"): ("floor_material", "single"),
    ("housing", "cooking_fuel"): ("cooking_fuel", "single"),
    ("housing", "lighting_source"): ("lighting_source", "single"),
    ("housing", "water_source"): ("water_source", "single"),
    ("housing", "toilet_type"): ("toilet_type", "single"),
    ("housing", "waste_disposal"): ("waste_disposal", "single"),
    ("housing", "share_toilet"): ("yes_no", "single"),
    ("housing", "livelihood_source"): ("livelihood_source", "single"),
    ("housing", "assets_owned"): ("asset_type", "multi"),
    # Agriculture / Livelihoods
    ("agriculture", "crop_production"): ("ag_activity", "single"),
    ("agriculture", "livestock"): ("ag_activity", "single"),
    ("agriculture", "ag_purpose"): ("ag_purpose", "single"),
    ("agriculture", "land_ownership"): ("land_ownership", "single"),
    ("agriculture", "title_deed"): ("title_deed", "single"),
    # Food & Shocks
    ("food_security", "main_food_source"): ("livelihood_source", "single"),
    ("shocks_coping", "shock_type"): ("shock_type", "multi"),
    ("shocks_coping", "coping_frequency"): ("coping_frequency", "single"),
    # Interview / Consent
    ("interview", "result"): ("interview_result", "single"),
    ("interview", "consent"): ("yes_no", "single"),
    # Per-member nested blocks
    ("members", "*", "sex"): ("sex", "single"),
    ("members", "*", "nationality"): ("nationality", "single"),
    ("members", "*", "marital_status"): ("marital_status", "single"),
    ("members", "*", "relationship_to_head"): ("relationship", "single"),
    ("members", "*", "birth_certificate_status"): ("birth_certificate", "single"),
    ("members", "*", "nin_status"): ("nin_status", "single"),
    ("members", "*", "education", "literacy"): ("literacy", "single"),
    ("members", "*", "education", "ever_school"): ("yes_no", "single"),
    ("members", "*", "education", "currently_attending"): ("yes_no", "single"),
    ("members", "*", "education", "education_level"): ("education_level", "single"),
    ("members", "*", "education", "never_school_reason"): ("never_school_reason", "single"),
    ("members", "*", "education", "stopped_school_reason"): ("stopped_school_reason", "single"),
    ("members", "*", "employment", "work_status"): ("work_status", "single"),
    ("members", "*", "employment", "main_job"): ("main_job", "single"),
    ("members", "*", "employment", "work_sector"): ("work_sector", "single"),
    ("members", "*", "employment", "work_frequency"): ("work_frequency", "single"),
    ("members", "*", "employment", "not_working_reason"): ("not_working_reason", "single"),
    ("members", "*", "health", "chronic_illness"): ("yes_no", "single"),
    ("members", "*", "health", "difficulty"): ("difficulty", "multi"),
    # OPEN ITEM OI-S22-3: the Washington Group disability dimensions
    # (seeing/hearing/walking/remembering/self_care/communicating)
    # and `severity` use codes 01/02/03/04 (None/Some/A lot/Cannot)
    # for which no ChoiceList is seeded — the seed `severity` list
    # carries codes 1/2/3 with different labels (Very severe / Severe /
    # Mild/moderate). Wiring these through the resolver against the
    # wrong list produced ref_data.unmapped_code log spam at every
    # household read (US-S22-005f regression). They are deliberately
    # left out of the map until a `wg_disability` ChoiceList is
    # authored and approved through the dual-approval workflow.
    # JSX falls back to the raw code, matching pre-005f behaviour.
    # Employment yes/no flags
    ("members", "*", "employment", "made_savings"): ("yes_no", "single"),
    # Top-level questionnaire yes/no flags
    ("shocks_coping", "shock_affected"): ("yes_no", "single"),
}


def apply_payload_labels(payload, resolver, *, as_of=None, language: str = "en"):
    """Walk `payload` (the canonical_payload JSON), producing a parallel
    tree of resolved labels for every path declared in PAYLOAD_FIELDS.

    `resolver` is the `resolve_label` callable (passed in so this
    module stays free of reference_data imports — keeps the
    dependency direction one-way, data_management → reference_data
    via the AppConfig wiring, never the other way).

    Returns a dict shaped like `payload` but containing only the
    coded fields (and ancestors needed to reach them), with each
    leaf replaced by its label (string) or list of labels (multi).
    Missing keys are skipped silently.
    """
    if not payload:
        return {}
    from .choice_field_map import PAYLOAD_FIELDS  # local for testability

    out: dict = {}
    for path, (list_name, kind) in PAYLOAD_FIELDS.items():
        _label_one_path(payload, path, out, list_name, kind, resolver, as_of, language)
    return out


def _label_one_path(node, path, out, list_name, kind, resolver, as_of, language):
    """Walk `node` along `path`, writing the leaf label into `out`
    at the same path. Caller invariant: `node` is whatever the path
    so far points to in the source payload; `out` is the matching
    container in the labels tree. `path` never starts with `"*"` at
    this entry — array steps are consumed inside the recursion.
    """
    if not path or not isinstance(node, dict):
        return
    head, *tail = path
    if not tail:
        raw = node.get(head)
        if raw is None or raw == "":
            return
        if kind == "multi":
            codes = raw.split() if isinstance(raw, str) else list(raw)
            out[head] = [resolver(list_name, c, language, as_of) for c in codes]
        else:
            out[head] = resolver(list_name, raw, language, as_of)
        return
    next_node = node.get(head)
    if next_node is None:
        return
    if tail[0] == "*":
        if not isinstance(next_node, list):
            return
        arr = out.setdefault(head, [])
        while len(arr) < len(next_node):
            arr.append({})
        rest = tail[1:]
        for i, item in enumerate(next_node):
            _label_one_path(item, rest, arr[i], list_name, kind, resolver, as_of, language)
    else:
        child_out = out.setdefault(head, {})
        _label_one_path(next_node, tail, child_out, list_name, kind, resolver, as_of, language)
