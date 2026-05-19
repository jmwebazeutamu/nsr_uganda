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
            {"key": "urban_rural", "label": "Urban / rural",     "type": "select", "pmt": True,
             "options": ["urban", "rural"]},
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
            {"key": "member_name",     "label": "Member name",             "type": "text",   "pmt": False},
            {"key": "member_dob",      "label": "Member date of birth",    "type": "date",   "pmt": False},
            {"key": "member_sex",      "label": "Member sex",              "type": "select", "pmt": False,
             "options": ["M", "F"]},
            {"key": "member_relation", "label": "Member relation to head", "type": "text",   "pmt": False},
        ],
    },
    {
        "key": "hd", "label": "Health & Disability", "tone": "danger",
        "fields": [
            {"key": "disab",     "label": "Disability status",          "type": "select", "pmt": True,
             "options": ["none", "mild", "moderate", "severe"]},
            {"key": "chronic",   "label": "Chronic illness",            "type": "select", "pmt": True,
             "options": ["yes", "no"]},
            {"key": "u5_breg",   "label": "Under-5 birth registration", "type": "select", "pmt": False,
             "options": ["yes", "no", "partial"]},
            {"key": "preg_lact", "label": "Pregnant / lactating",       "type": "select", "pmt": False,
             "options": ["yes", "no"]},
        ],
    },
    {
        "key": "ed", "label": "Education", "tone": "programme",
        "fields": [
            {"key": "ever_school", "label": "Ever attended school", "type": "select", "pmt": True,
             "options": ["yes", "no"]},
            {"key": "grade",       "label": "Highest grade",        "type": "text",   "pmt": True},
            {"key": "attending",   "label": "Currently attending",  "type": "select", "pmt": False,
             "options": ["yes", "no"]},
        ],
    },
    {
        "key": "emp", "label": "Employment", "tone": "system",
        "fields": [
            {"key": "occ",        "label": "Primary occupation",  "type": "text",   "pmt": True},
            {"key": "sector",     "label": "Sector",              "type": "select", "pmt": True,
             "options": ["agriculture", "trade", "services", "manufacturing",
                         "public", "none"]},
            {"key": "income_src", "label": "Main income source",  "type": "text",   "pmt": True},
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
