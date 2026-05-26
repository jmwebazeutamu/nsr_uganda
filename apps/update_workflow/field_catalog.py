"""US-S22-003 — Open-CR modal field catalog.

Mirror of `design/v0.1/components/change-request-modal.jsx`'s catalog.
The bundle endpoint validates incoming `rows` against this — drift
between the two would let the modal send fields the server doesn't
recognise. tests.test_field_catalog_parity guards the match.

Each category carries:
- key          short code used in payloads ("iden", "loc", "rost", …)
- label        operator-facing category name
- tone         design-token accent for chips / category strips
- fields       list of {key, label, type, pmt, options?}

`pmt` is the per-field flag: when any selected row carries pmt=True
the bundle endpoint auto-derives `pmt_relevant=True` (the modal
mirrors this and disables the Force-PMT checkbox while it's true).

`entity` is the per-field scope flag ("household" or "member").
Missing = "household" (default). Member-scope fields can only be
submitted with entity="member" in the bundle payload + a member_id
that belongs to the household. Enforced in `validate_member_field`.
"""

from __future__ import annotations

CATEGORIES: list[dict] = [
    {
        "key": "iden", "label": "Identification", "tone": "identity",
        "fields": [
            {"key": "phone",     "label": "Phone",                "type": "text",   "pmt": False},
            {"key": "email",     "label": "Email",                "type": "text",   "pmt": False},
            {"key": "head_name", "label": "Head of household",    "type": "text",   "pmt": False},
            {"key": "head_nin",  "label": "Head NIN",             "type": "text",   "pmt": False},
            {"key": "lang",      "label": "Preferred language",   "type": "select", "pmt": False,
             "options": ["English", "Luganda", "Swahili", "Acholi", "Karamojong",
                         "Lugbara", "Runyankole"]},
        ],
    },
    {
        "key": "loc", "label": "Location", "tone": "data",
        "fields": [
            {"key": "gps",         "label": "GPS coordinates",   "type": "text",   "pmt": False},
            {"key": "ea",          "label": "Enumeration area",  "type": "text",   "pmt": False},
            # ADR-0010: urban_rural is a coded ChoiceList field — options
            # MUST be the seed codes (rural_urban: 1=Urban, 2=Rural). The
            # display label is resolved by the resolver at render time.
            {"key": "urban_rural", "label": "Urban / rural",     "type": "select", "pmt": True,
             "options": ["1", "2"]},
            {"key": "village",     "label": "Village",           "type": "text",   "pmt": False},
            {"key": "parish",      "label": "Parish",            "type": "text",   "pmt": False},
        ],
    },
    {
        "key": "rost", "label": "Roster", "tone": "update",
        "fields": [
            {"key": "hh_size",         "label": "Household size",          "type": "number", "pmt": True},
            {"key": "add_member",      "label": "Add member (name)",       "type": "text",   "pmt": False},
            {"key": "remove_member",   "label": "Remove member (line #)",  "type": "number", "pmt": False},
            {"key": "member_name",     "label": "Member name",             "type": "text",
             "pmt": False, "entity": "member"},
            {"key": "member_dob",      "label": "Member date of birth",    "type": "date",
             "pmt": False, "entity": "member"},
            # ADR-0010: member_sex is a coded ChoiceList field — options
            # MUST be the seed codes (sex: 1=Male, 2=Female).
            {"key": "member_sex",      "label": "Member sex",              "type": "select",
             "pmt": False, "options": ["1", "2"], "entity": "member"},
            {"key": "member_relation", "label": "Member relation to head", "type": "text",
             "pmt": False, "entity": "member"},
        ],
    },
    {
        "key": "hd", "label": "Health & Disability", "tone": "danger",
        "fields": [
            {"key": "disab",     "label": "Disability status",          "type": "select", "pmt": True,
             "options": ["none", "mild", "moderate", "severe"], "entity": "member"},
            {"key": "chronic",   "label": "Chronic illness",            "type": "select", "pmt": True,
             "options": ["yes", "no"], "entity": "member"},
            {"key": "u5_breg",   "label": "Under-5 birth registration", "type": "select", "pmt": False,
             "options": ["yes", "no", "partial"], "entity": "member"},
            {"key": "preg_lact", "label": "Pregnant / lactating",       "type": "select", "pmt": False,
             "options": ["yes", "no"], "entity": "member"},
        ],
    },
    {
        "key": "ed", "label": "Education", "tone": "programme",
        "fields": [
            {"key": "ever_school", "label": "Ever attended school", "type": "select", "pmt": True,
             "options": ["yes", "no"], "entity": "member"},
            {"key": "grade",       "label": "Highest grade",        "type": "text",   "pmt": True, "entity": "member"},
            {"key": "attending",   "label": "Currently attending",  "type": "select", "pmt": False,
             "options": ["yes", "no"], "entity": "member"},
        ],
    },
    {
        "key": "emp", "label": "Employment", "tone": "system",
        "fields": [
            {"key": "occ",        "label": "Primary occupation",  "type": "text",   "pmt": True, "entity": "member"},
            {"key": "sector",     "label": "Sector",              "type": "select", "pmt": True,
             "options": ["agriculture", "trade", "services", "manufacturing",
                         "public", "none"], "entity": "member"},
            {"key": "income_src", "label": "Main income source",  "type": "text",   "pmt": True, "entity": "member"},
        ],
    },
    {
        "key": "hous", "label": "Housing & Assets", "tone": "eligibility",
        "fields": [
            {"key": "roof",        "label": "Roof material",     "type": "select", "pmt": True,
             "options": ["Iron sheets", "Tiles", "Thatch", "Asbestos", "Other"]},
            {"key": "wall",        "label": "Wall material",     "type": "select", "pmt": True,
             "options": ["Brick", "Mud", "Wood", "Iron sheets", "Other"]},
            {"key": "floor",       "label": "Floor material",    "type": "select", "pmt": True,
             "options": ["Cement", "Earth", "Tiles", "Wood", "Other"]},
            {"key": "water",       "label": "Water source",      "type": "select", "pmt": True,
             "options": ["Tap", "Borehole", "Spring", "River", "Vendor", "Other"]},
            {"key": "toilet",      "label": "Toilet type",       "type": "select", "pmt": True,
             "options": ["Flush", "Pit (covered)", "Pit (open)", "None", "Other"]},
            {"key": "fuel",        "label": "Cooking fuel",      "type": "select", "pmt": True,
             "options": ["Firewood", "Charcoal", "Gas", "Electricity", "Other"]},
            {"key": "light",       "label": "Lighting source",   "type": "select", "pmt": True,
             "options": ["Electricity", "Solar", "Kerosene", "Candle", "Other"]},
            {"key": "tenure",      "label": "Dwelling tenure",   "type": "select", "pmt": True,
             "options": ["Owned", "Rented", "Free", "Other"]},
            {"key": "land_acres",  "label": "Land owned (acres)", "type": "number", "pmt": True},
            {"key": "cattle",      "label": "Cattle owned",       "type": "number", "pmt": True},
            {"key": "goats",       "label": "Goats owned",        "type": "number", "pmt": True},
            {"key": "radio",       "label": "Owns radio",         "type": "select", "pmt": True,
             "options": ["yes", "no"]},
            {"key": "tv",          "label": "Owns TV",            "type": "select", "pmt": True,
             "options": ["yes", "no"]},
            {"key": "phone_owned", "label": "Owns phone",         "type": "select", "pmt": True,
             "options": ["yes", "no"]},
        ],
    },
    {
        "key": "food", "label": "Food & Shocks", "tone": "quality",
        "fields": [
            {"key": "meals",  "label": "Meals per day",            "type": "number", "pmt": True},
            {"key": "fcs",    "label": "Food consumption score",   "type": "number", "pmt": True},
            {"key": "shock",  "label": "Recent shock",             "type": "select", "pmt": True,
             "options": ["drought", "flood", "death_head", "theft", "illness",
                         "none", "other"]},
            {"key": "coping", "label": "Coping strategy",          "type": "select", "pmt": True,
             "options": ["asset_sale", "reduce_meals", "skip_meal", "borrow",
                         "migrate", "none", "other"]},
        ],
    },
]


def category_keys() -> set[str]:
    return {c["key"] for c in CATEGORIES}


def field_keys_by_category() -> dict[str, set[str]]:
    return {c["key"]: {f["key"] for f in c["fields"]} for c in CATEGORIES}


def is_pmt_relevant(category: str, field: str) -> bool:
    for c in CATEGORIES:
        if c["key"] != category:
            continue
        for f in c["fields"]:
            if f["key"] == field:
                return bool(f["pmt"])
        return False
    return False


def validate_row(category: str, field: str) -> None:
    """Raise ValueError if (category, field) isn't in the catalog."""
    pairs = field_keys_by_category()
    if category not in pairs:
        raise ValueError(f"unknown category {category!r}")
    if field not in pairs[category]:
        raise ValueError(f"unknown field {field!r} for category {category!r}")


def field_entity(category: str, field: str) -> str:
    """Return 'household' or 'member' for the given field.

    Missing `entity` key in the catalog → 'household' (the default —
    used by every legacy field that pre-dated the member-scope split).
    """
    for c in CATEGORIES:
        if c["key"] != category:
            continue
        for f in c["fields"]:
            if f["key"] == field:
                return f.get("entity", "household")
    return "household"


def member_field_pairs() -> set[tuple[str, str]]:
    """All (category, field) pairs whose entity scope is 'member'."""
    out: set[tuple[str, str]] = set()
    for c in CATEGORIES:
        for f in c["fields"]:
            if f.get("entity") == "member":
                out.add((c["key"], f["key"]))
    return out
