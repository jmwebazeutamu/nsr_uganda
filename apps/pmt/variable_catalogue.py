"""What a PMT variable may be built from, derived from canonical sources.

The Configuration screen needs two things it was previously inventing:
the set of fields a variable can score, and — for a coded field — the
values it may test. Both already exist elsewhere and neither belongs in
JSX:

* which fields exist, and what they are called, comes from the engine's
  own feature tree crossed with `FormQuestion` (see `docs/ssot_register.md`:
  questionnaire variables are `apps.intake.models.FormQuestion`);
* which values a coded field may hold comes from
  `FormQuestion.choice_list_ref -> ChoiceList -> ChoiceOption`, the same
  chain `apps.pmt.coded_operands` validates against (ADR-0041).

So the catalogue is assembled, not authored. The only thing stated here
is `ROOTS` — the engine's feature-tree prefixes — because that mapping
is the engine's contract and lives nowhere else.

Naming
------
A variable is named after the canonical field it scores, so the binding
is readable straight off the model:

    floor_material__tiles_terrazzo   ->  dwelling.floor_material

Several variables legitimately score one field: the education, wall,
floor and lighting variables are cumulative ladders with different code
ranges and different weights. The qualifier after `__` distinguishes
them while keeping the binding as the prefix, and keeps names unique,
which the table keys, the duplicate check and the CSV import all rely
on. `canonical_name()` is the one place that spelling is decided.
"""

from __future__ import annotations

#: Feature-tree prefix -> the model whose columns hang off it.
#:
#: These are exactly the keys `engine._household_features()` returns for
#: the one-to-one detail entities, which is why a variable's path reads
#: `dwelling.floor_material` and not `household.dwelling.floor_material`.
#: `test_catalogue_roots_match_the_engine` pins them against a real
#: computed feature dict, so this cannot drift from the engine in
#: silence.
ROOTS: tuple[tuple[str, str, str], ...] = (
    # (feature-tree prefix, "app_label.ModelName", operator-facing group)
    ("household", "data_management.Household", "Household"),
    ("head_member", "data_management.Member", "Head of household"),
    ("head_member.education", "data_management.Education", "Education"),
    ("head_member.employment", "data_management.Employment", "Employment"),
    ("head_member.health", "data_management.Health", "Health"),
    ("dwelling", "data_management.Dwelling", "Dwelling"),
    ("utilities", "data_management.Utilities", "Utilities"),
    ("livelihood", "data_management.Livelihood", "Livelihood"),
    ("food_security", "data_management.FoodSecurity", "Food security"),
    ("food_consumption", "data_management.FoodConsumption", "Food consumption"),
)

#: Scalars the engine computes rather than reads from a column, with the
#: path they answer to. These have no questionnaire binding by
#: definition — `member_count` is not a question anyone was asked — so
#: they are listed here and marked `derived`, not hunted for in
#: `FormQuestion`. `test_declared_derived_features_exist` pins every one
#: against a real feature dict.
DERIVED: tuple[dict[str, str], ...] = (
    {"name": "member_count", "label": "Household size",
     "help": "Number of members on the roster."},
    {"name": "disabled_member_count", "label": "Members with a disability",
     "help": "Members carrying the Washington Group disability flag."},
    {"name": "chronic_ill_member_count", "label": "Members chronically ill",
     "help": "Members with an affirmative chronic-illness flag."},
    {"name": "school_age_out_of_school_count", "label": "School-age out of school",
     "help": "Members aged 6-18 not currently attending."},
    {"name": "dependency_ratio", "label": "Dependency ratio",
     "help": "(under 15 + over 65) / working age, 0 when no working-age member."},
)


def canonical_name(field: str, qualifier: str = "") -> str:
    """The name a variable scoring `field` is given.

    One spelling rule, one place. A qualifier is appended after `__`
    when several variables score the same field.
    """
    field = (field or "").strip()
    qualifier = (qualifier or "").strip().strip("_")
    return f"{field}__{qualifier}" if qualifier else field


def field_for_name(name: str) -> str:
    """The canonical field a variable name refers to — the inverse of
    `canonical_name`. Unqualified names are their own field."""
    return (name or "").split("__", 1)[0]


def _questions_by_field():
    """canonical_field (and declared aliases) -> FormQuestion.

    Shares the resolution rule with `apps.pmt.coded_operands` — a path
    leaf resolves through `canonical_field` first and `payload_aliases`
    second — so the catalogue offers exactly the fields the activation
    gate can check.
    """
    from apps.intake.models import FormQuestion

    index: dict[str, object] = {}
    questions = (
        FormQuestion.objects
        .exclude(canonical_field="")
        .select_related("choice_list_ref")
        .order_by("section__order", "order_in_section")
    )
    for question in questions:
        for key in [question.canonical_field, *(question.payload_aliases or [])]:
            if key:
                index.setdefault(str(key), question)
    return index


def _options_for(question) -> list[dict[str, str]]:
    from apps.reference_data.models import ChoiceOption

    if not question.choice_list_ref_id:
        return []
    rows = (
        ChoiceOption.objects
        .filter(
            choice_list=question.choice_list_ref,
            status=ChoiceOption.Status.ACTIVE,
        )
        .order_by("sort_order", "code")
        .values_list("code", "label")
    )
    return [{"code": code, "label": label} for code, label in rows]


def catalogue() -> dict:
    """Every field a PMT variable may score, and its permitted values.

    Fields the engine can reach but the questionnaire does not describe
    are omitted rather than guessed at: a field with no canonical
    question has no authority for its values, and offering it would
    invite exactly the free-typed codes ADR-0041 exists to stop.
    """
    from django.apps import apps as django_apps

    questions = _questions_by_field()
    fields: list[dict] = []
    seen: set[str] = set()

    for prefix, model_label, group in ROOTS:
        try:
            model = django_apps.get_model(model_label)
        except LookupError:
            # A root naming a model that no longer exists is a real
            # problem, but not one the Configuration screen should die
            # of. test_catalogue_roots_match_the_engine reports it.
            continue
        for column in model._meta.get_fields():
            name = getattr(column, "name", None)
            if not name or name in seen:
                continue
            question = questions.get(name)
            if question is None:
                continue
            options = _options_for(question)
            seen.add(name)
            fields.append({
                "field": name,
                "name": canonical_name(name),
                "label": question.label or name,
                "path": f"{prefix}.{name}",
                "group": group,
                "question": question.name,
                "kind": "coded" if options else "value",
                "choice_list": (
                    question.choice_list_ref.list_name
                    if question.choice_list_ref_id else ""
                ),
                "options": options,
            })

    fields.sort(key=lambda f: (f["group"], f["label"]))

    derived = [
        {
            "field": entry["name"],
            "name": entry["name"],
            "label": entry["label"],
            "path": entry["name"],
            "group": "Derived from the household",
            "question": "",
            "kind": "derived",
            "choice_list": "",
            "options": [],
            "help": entry["help"],
        }
        for entry in DERIVED
    ]

    return {"fields": fields, "derived": derived}
