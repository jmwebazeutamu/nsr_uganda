"""Public questionnaire catalogue — the citizen-facing transparency
surface. ADR-0023 (public-discovery extension, US-DATA-EXP-001).

The goal is openness about *what the registry captures*, so a member of
the public can see the full data dictionary and decide to request access
via a Data Sharing Agreement. This is deliberately a different source
from the aggregate catalogue (the Variable table):

- The Variable table is the *aggregate* surface — only fields loaded and
  dual-approved for matview-backed querying appear, and it is
  EXPLORER-gated.
- This module is the *transparency* surface — the ENTIRE questionnaire,
  every section and field, driven straight from
  apps.update_workflow.field_catalog (which introspects the DAT models)
  plus the default privacy classification.

It exposes METADATA ONLY: field id, label, type, questionnaire section,
privacy class, and whether the field is ever aggregatable. It never
exposes household records or cell counts — record-level access is the
DRS handoff, and aggregate counts are the EXPLORER-gated /aggregate
endpoint. No DB access is required (it reads the field-catalog feed and
the seed-default privacy map), so it works on a fresh, unmigrated DB.
"""

from __future__ import annotations

from .seeds.privacy_class_defaults import PRIVACY_CLASS_DEFAULTS, classify

# Code → display + suppression knobs, from the single seed source.
_PRIVACY_META = {
    row["code"]: {
        "label": row["label"],
        "description": row["description"],
        "k_floor": row["k_floor"],
        "blocks_aggregate": row["blocks_aggregate"],
    }
    for row in PRIVACY_CLASS_DEFAULTS
}

NOTICE = (
    "Metadata only — this lists the questions the National Social "
    "Registry captures and how each field is protected. It does not "
    "expose any household's records or counts. Record-level access is "
    "granted only under a Data Sharing Agreement; aggregate statistics "
    "are available to authorised analysts."
)


def _field_entry(category_key: str, f: dict) -> dict:
    pc_code = classify(category_key, f["key"])
    meta = _PRIVACY_META.get(pc_code, _PRIVACY_META["internal"])
    entry = {
        "field_id": f["field_id"],
        "label": f["label"],
        "type": f["type"],
        "privacy_class": pc_code,
        "privacy_label": meta["label"],
        # A sensitive field is never aggregatable; everything else is,
        # subject to k-anonymity suppression at its floor.
        "aggregatable": not meta["blocks_aggregate"],
        "k_floor": meta["k_floor"],
        "pmt_relevant": bool(f.get("pmt")),
    }
    if f.get("choice_list"):
        entry["choice_list"] = f["choice_list"]
    return entry


def build() -> dict:
    """Return the full public catalogue: every questionnaire section and
    field, badged by privacy class. Metadata only."""
    from apps.update_workflow import field_catalog

    sections = []
    totals_by_privacy: dict[str, int] = {c: 0 for c in _PRIVACY_META}
    total_fields = 0

    for category in field_catalog.categories():
        fields = [_field_entry(category["key"], f) for f in category["fields"]]
        summary = {c: 0 for c in _PRIVACY_META}
        for fe in fields:
            summary[fe["privacy_class"]] += 1
            totals_by_privacy[fe["privacy_class"]] += 1
        total_fields += len(fields)
        sections.append({
            "key": category["key"],
            "label": category["label"],
            "entity": category.get("entity", ""),
            "questionnaire_section": category.get("questionnaire_section", ""),
            "field_count": len(fields),
            "privacy_summary": summary,
            "fields": fields,
        })

    return {
        "sections": sections,
        "totals": {
            "sections": len(sections),
            "fields": total_fields,
            "by_privacy": totals_by_privacy,
        },
        "privacy_classes": [
            {
                "code": code,
                "label": m["label"],
                "description": m["description"],
                "k_floor": m["k_floor"],
                "aggregatable": not m["blocks_aggregate"],
            }
            for code, m in _PRIVACY_META.items()
        ],
        "notice": NOTICE,
    }
