"""The DSA field-group vocabulary. One definition.

A Data Sharing Agreement grants a partner access by **group** —
`{"Identifiers": true, "PMT": true}` — while a data request names
**field paths**, `household.sub_region_code`. `builder_schema
.FIELD_CATALOGUE` is the only maintained mapping between the two, so
the groups are derived from it here rather than listed again.

They were listed again. Three times, and the three disagreed:

  * the catalogue said `Members`, `Utilities`, `Dwelling`,
    `Food consumption`, `Food security`;
  * `screens-dsas.jsx` offered `Roster`, `Housing`, `FoodShocks`;
  * `scope-edit-modal.jsx` offered the same eight as the screen.

So a DSA written through the console granted `Roster` and the validator
looked for `Members`, found nothing, and refused the partner's request
as "outside DSA scope" — which reads like the partner asked for
something they were not given. Production holds two such agreements.

Worse in the other direction: the console never offered **Geography**
at all, so no agreement created through the UI could grant it. That is
the end-to-end DRS test's failure, in production form.

What this module is NOT
-----------------------
It is not a second field dictionary. The fields, their labels, their
types and their sensitivity all come from FIELD_CATALOGUE; this only
names the groups that catalogue already uses, and attaches the
operator-facing description of each.

Open schema dependency
----------------------
The disclosure group is a real concept with no home in the
Questionnaire Authoring dictionary — that dictionary's `section` is a
questionnaire section (Identification, Roster, Health), which is a
different axis from "what may a partner receive". Until the Schema
Registry carries a disclosure classification, FIELD_CATALOGUE is the
registry for it, and this module is how everything else reads it.
See the note in ADR-0040.
"""

from __future__ import annotations

from typing import Any

#: Operator-facing description per group. A group with no entry here
#: still exists and is still grantable — it simply shows with its bare
#: name, which is a missing sentence rather than a missing feature.
DESCRIPTIONS: dict[str, str] = {
    "Identifiers": "Registry ID, household number, enumeration area",
    "Geography": "Region through village, and the GPS point",
    "PMT": "Vulnerability score and band",
    "Members": "Household roster — head, members, ages, relationships",
    "Health": "Chronic illness flags and types",
    "Education": "Literacy, attendance, highest grade",
    "Employment": "Main activity, sector, employment status",
    "Dwelling": "Tenure, dwelling type, rooms, construction",
    "Utilities": "Water, sanitation, lighting, cooking fuel",
    "Livelihood": "Main livelihood, land ownership and use",
    "Food consumption": "Food Consumption Score and its components",
    "Food security": "FIES score and its components",
    "Programmes": "Programme codes the household is enrolled in",
    "Lifecycle": "Consent state, intake source, record timestamps",
}

#: What the console used to write -> what the catalogue calls it.
#:
#: Kept so an agreement signed under the old vocabulary keeps meaning
#: what it meant. `Housing` and `FoodShocks` each covered two catalogue
#: groups, so they expand rather than rename — narrowing a signed
#: agreement is not a migration's decision to make.
LEGACY_ALIASES: dict[str, tuple[str, ...]] = {
    "Roster": ("Members",),
    "Housing": ("Dwelling", "Utilities"),
    "FoodShocks": ("Food consumption", "Food security"),
}


def canonical_groups() -> list[str]:
    """Every group the catalogue uses, in catalogue order."""
    from .builder_schema import FIELD_CATALOGUE

    seen: list[str] = []
    for field in FIELD_CATALOGUE:
        group = field.get("group")
        if group and group not in seen:
            seen.append(group)
    return seen


def group_for_key(key: str) -> str | None:
    """The group a field path belongs to, or None if the catalogue
    does not carry that path."""
    from .builder_schema import FIELD_CATALOGUE

    for field in FIELD_CATALOGUE:
        if field.get("key") == key:
            return field.get("group")
    return None


def keys_in_group(group: str) -> list[str]:
    from .builder_schema import FIELD_CATALOGUE

    return [f["key"] for f in FIELD_CATALOGUE if f.get("group") == group]


def catalogue() -> list[dict[str, Any]]:
    """The groups, as the console renders them.

    Served over the API so the console has no list of its own. Each
    entry carries the field count, because "Geography (11 fields)" is
    the difference between an informed grant and a guess.
    """
    from .builder_schema import FIELD_CATALOGUE

    counts: dict[str, int] = {}
    entities: dict[str, set[str]] = {}
    for field in FIELD_CATALOGUE:
        group = field.get("group")
        if not group:
            continue
        counts[group] = counts.get(group, 0) + 1
        entities.setdefault(group, set()).add(str(field["key"]).partition(".")[0])

    return [
        {
            "key": group,
            "label": group,
            "description": DESCRIPTIONS.get(group, ""),
            "field_count": counts[group],
            "entities": sorted(entities[group]),
        }
        for group in canonical_groups()
    ]


def normalise(scope: dict | None) -> dict[str, bool]:
    """A stored `field_scope` in the canonical vocabulary.

    Legacy names expand to the groups they covered; anything already
    canonical passes through; anything the catalogue has never heard of
    is dropped, because a grant nothing can resolve authorises nothing
    and keeping it only makes the agreement look wider than it is.
    """
    if not scope:
        return {}
    known = set(canonical_groups())
    out: dict[str, bool] = {}
    for name, granted in scope.items():
        targets = LEGACY_ALIASES.get(name, (name,))
        for target in targets:
            if target in known:
                # A group granted under either name stays granted.
                out[target] = bool(granted) or out.get(target, False)
    return out


def unknown_groups(scope: dict | None) -> list[str]:
    """Names in `scope` that neither the catalogue nor the aliases
    resolve — what a health check should report."""
    if not scope:
        return []
    known = set(canonical_groups())
    return sorted(
        name for name in scope
        if name not in known and name not in LEGACY_ALIASES
    )
