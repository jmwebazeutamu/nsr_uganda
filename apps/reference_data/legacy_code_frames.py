"""The legacy → UBOS 2024 choice-code mapping, and what is not mappable.

Six housing lists and two employment lists each carry TWO code frames at
once: a legacy single-digit frame (1–8) and the UBOS 2024 frame (00–24,
96, 98). The lists render merged, so the capture wizard offered the
enumerator pairs like:

    Dwelling type   "Detached" (1)     and "Detached house (Bungalow)" (11)
    Roof material   "Iron sheets" (1)  and "Iron sheets" (11)
    Floor material  "Tiles" (2)        and "Tiles" (17)

Two enumerators coding the same hut produce different values, and no
analysis downstream can tell whether that is a real difference between
two households or two people picking different rows from the same list.

Only the UBOS 2024 frame is seeded (apps/reference_data/seeds/
choice_lists_v1.json). The single-digit rows exist in the database
alone, left over from an earlier seed, so this is data debt with no
code to delete.

RESOLUTION
----------
UBOS 2024 is the surviving frame. Legacy options are DEPRECATED, not
deleted — ChoiceOption's documented contract is that a deprecated code
stays readable for historical records but is not selectable on a new
intake, and the bundle endpoint already filters `status != ACTIVE`, so
deprecating removes them from every dropdown with no UI change.

EXACT vs AMBIGUOUS
------------------
`EXACT` holds only pairs where the legacy label and the UBOS label
denote the same thing, so rewriting a stored value changes no meaning.
Those are migrated.

`AMBIGUOUS` holds legacy codes with no single UBOS counterpart — either
the UBOS frame splits the legacy category across several codes, or it
has no equivalent at all. These are NOT rewritten. Guessing here would
put a fabricated answer into a household's record and then into its PMT
score. The option row is deprecated (so nobody can pick it again) and
the stored value is left alone until MGLSD signs off a mapping; the
label stays resolvable because the deprecated option row survives.

`cooking_fuel` is deliberately almost entirely in AMBIGUOUS: the two
lists are not two frames of one variable. The legacy list codes the
FUEL (firewood, charcoal, paraffin); UBOS 2024 codes the STOVE
(three-stone open fire, LPG stove, electric stove). Mapping "Firewood"
onto "Three stone stove/open fire" would assert a stove type nobody was
ever asked about.

Report what is left with:
    python manage.py report_legacy_choice_codes

See ADR-0032.
"""

from __future__ import annotations

# list_name -> {legacy_code: ubos_code}. Same meaning, both directions.
EXACT: dict[str, dict[str, str]] = {
    "dwelling_type": {
        "1": "11",   # Detached                -> Detached house (Bungalow)
        "2": "12",   # Semi-detached           -> Semi-detached house
        "3": "13",   # Flat                    -> Apartment/Condominium
        "4": "16",   # Tenement                -> Tenement (Muzigo)
        "5": "17",   # Hut                     -> Hut
    },
    "roof_material": {
        "1": "11",   # Iron sheets             -> Iron sheets
        "2": "12",   # Tiles                   -> Tiles
        "3": "14",   # Concrete                -> Concrete
        "4": "16",   # Thatch / grass          -> Thatch/Dry leaves
    },
    "wall_material": {
        "3": "16",   # Wood                    -> Wood
        "4": "19",   # Iron sheets             -> Iron sheets
        "5": "11",   # Concrete / stone        -> Concrete/Stones
        "6": "21",   # Thatch / grass          -> Thatch/Dry leaves/Papyrus
    },
    "floor_material": {
        "1": "14",   # Cement / screed         -> Cement screed
        "2": "17",   # Tiles                   -> Tiles
        "3": "15",   # Earth - rammed          -> Rammed earth
        "4": "16",   # Wood                    -> Wood
        "5": "12",   # Bricks                  -> Brick
    },
    "cooking_fuel": {
        "8": "96",   # Other                   -> Other
    },
    "waste_disposal": {
        "2": "12",   # Burned                  -> Burn solid waste
        "8": "96",   # Other                   -> Other arrangements
    },
    "work_frequency": {
        "1": "01",   # Full-time               -> Full time - permanent work
        "2": "02",   # Part-time               -> Part time - permanent work
        "3": "05",   # Occasional              -> Occasionally
    },
    "not_working_reason": {
        "1": "03",   # Studying                -> Student
        "5": "02",   # Too young               -> Age too old/too young
        "6": "01",   # Could not find work     -> No job available
        "98": "96",  # Other                   -> Other
    },
}

# list_name -> {legacy_code: why it cannot be rewritten}. Deprecated but
# never rewritten. Each of these needs an MGLSD/UBOS decision.
AMBIGUOUS: dict[str, dict[str, str]] = {
    "dwelling_type": {
        "6": "Tent — the UBOS 2024 frame has no tent category.",
        "8": "Other — the UBOS 2024 dwelling frame has no Other code.",
    },
    "roof_material": {
        "5": "Mud / dung — no UBOS 2024 equivalent.",
        "8": "Other — the UBOS 2024 roof frame has no Other code.",
    },
    "wall_material": {
        "1": "Brick (burnt / unburnt) — UBOS splits this across 13 "
             "(burnt, mud/cement), 14 (unburnt, cement) and 15 "
             "(unburnt, mud). The legacy code does not say which.",
        "2": "Mud — UBOS's nearest is 17 'Mud and Pole', which asserts a "
             "pole frame the legacy code never recorded.",
        "8": "Other — the UBOS 2024 wall frame has no Other code.",
    },
    "floor_material": {
        "8": "Other — the UBOS 2024 floor frame has no Other code.",
    },
    "cooking_fuel": {
        "1": "Firewood — a fuel. UBOS 2024 codes the stove, not the fuel.",
        "2": "Charcoal — a fuel; see above.",
        "3": "LPG / gas — a fuel; 04 is the LPG STOVE, not the fuel.",
        "4": "Electricity — a fuel; 02 is the electric STOVE.",
        "5": "Kerosene / paraffin — a fuel; 07 is the liquid-fuel STOVE.",
        "6": "Crop residue / dung — a fuel with no UBOS stove counterpart.",
    },
    "waste_disposal": {
        "1": "Collected by service — UBOS distinguishes a waste vendor (16) "
             "from a supervised municipal dump (14).",
        "3": "Buried — UBOS's 13 is 'Rubbish pit (burn/bury)', which "
             "conflates burning and burying.",
        "4": "Composted — no UBOS 2024 equivalent.",
        "5": "Dumped in pit — indistinguishable from legacy 3 under UBOS 13.",
        "6": "Dumped in open — UBOS's nearest, 18 'Bush', is narrower.",
    },
    "work_frequency": {
        "4": "Seasonal — UBOS splits seasonal work into full-time (03) and "
             "part-time (04). The legacy code does not say which.",
        "5": "Casual / day labour — arguably 05 'Occasionally', but casual "
             "day labour can be daily work; not the same claim.",
    },
    "not_working_reason": {
        "2": "Household duties — no UBOS 2024 equivalent. Mapping it to 06 "
             "'Not looking for a job' asserts a labour-market status the "
             "respondent was never asked about.",
        "3": "Illness / disability — UBOS splits illness/injury (04) from "
             "disability (05). The legacy code does not say which.",
        "4": "Retired / too old — UBOS's 02 is 'Age too old/too young', "
             "which loses 'retired'.",
    },
}

#: Every list carrying both frames.
AFFECTED_LISTS: tuple[str, ...] = tuple(EXACT)

#: Model fields storing a code from one of these lists, as
#: (app_label, model_name, field_name, list_name). Version tables are
#: included: a household's history must read the same way as its
#: current row.
CODED_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("data_management", "Dwelling", "dwelling_type", "dwelling_type"),
    ("data_management", "Dwelling", "roof_material", "roof_material"),
    ("data_management", "Dwelling", "wall_material", "wall_material"),
    ("data_management", "Dwelling", "floor_material", "floor_material"),
    ("data_management", "DwellingVersion", "dwelling_type", "dwelling_type"),
    ("data_management", "DwellingVersion", "roof_material", "roof_material"),
    ("data_management", "DwellingVersion", "wall_material", "wall_material"),
    ("data_management", "DwellingVersion", "floor_material", "floor_material"),
    ("data_management", "Utilities", "cooking_fuel", "cooking_fuel"),
    ("data_management", "Utilities", "waste_disposal", "waste_disposal"),
    ("data_management", "UtilitiesVersion", "cooking_fuel", "cooking_fuel"),
    ("data_management", "UtilitiesVersion", "waste_disposal", "waste_disposal"),
    ("data_management", "Employment", "work_frequency", "work_frequency"),
    ("data_management", "Employment", "not_working_reason", "not_working_reason"),
    ("data_management", "EmploymentVersion", "work_frequency", "work_frequency"),
    ("data_management", "EmploymentVersion", "not_working_reason", "not_working_reason"),
)


def legacy_codes(list_name: str) -> set[str]:
    """Every code on `list_name` that belongs to the retired frame."""
    return set(EXACT.get(list_name, {})) | set(AMBIGUOUS.get(list_name, {}))
