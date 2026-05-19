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
