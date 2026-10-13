"""Check a PMT model's coded values against the canonical question record.

A PMT variable tests a coded field by naming the codes directly::

    {"name": "head_edu_tertiary", "weight": 0.312,
     "feature": {"path": "head_member.education.highest_grade",
                 "type": "membership", "operand": ["17", ..., "23"]}}

Nothing tied those strings to the code list they are drawn from. There is
no FK on the model, and `feature_evaluator.validate_feature` is a static
JSON check that never reaches the database. `_h_membership` returns 0.0
when no code matches, so a wrong code is not an error — it is a variable
that silently scores zero for every household, forever.

That is not hypothetical. The seeded v1 model asks for `"4"` and `"8"` on
`education_level`, whose codes are zero-padded (`04` = P1, `08` = P5), so
`head_edu_completed_primary` and `head_edu_secondary` match nothing and
collapse onto `head_edu_tertiary`. On dev that scores 233 household heads
who finished P7 or secondary school as having no education at all, and
two weights that should stack never apply.

The authority
-------------
`FormQuestion` is the canonical question record.
`FormQuestion.choice_list_ref -> ChoiceList -> ChoiceOption` is the only
statement of which codes a coded field may hold. This module resolves a
feature's field to its question and checks the codes against that list —
it does not keep a list of its own, and it deliberately does NOT consult
`data_management.choice_field_map`, which names a different list for the
same field in at least five cases (`highest_grade` -> `education_level`
vs `highest_grade`, `toilet_facility` -> `toilet_type` vs
`toilet_facility`, and so on). One authority, not two.

Errors versus unresolved
------------------------
A code the question's list does not carry is an **error**: the binding
exists and the value contradicts it, which is exactly the case that
otherwise fails silently.

A field with no canonical question at all is **unresolved** and reported
without blocking. `presence_in_collection` filters on ORM field names
(`asset_type__in`) rather than canonical fields, and the asset question's
`canonical_field` is `assets_owned`, so the binding genuinely is not
there yet. Blocking on it would stop every model activating until the
questionnaire is extended, and guessing the list from somewhere else is
the duplicate-vocabulary defect this module exists to close. It is
reported so it can be fixed, per the standing rule that a missing
contract is surfaced rather than substituted.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

#: Filter lookups whose right-hand side is a code (or list of codes)
#: rather than a magnitude. `age_years__lt: 15` is not a code test.
_CODE_LOOKUPS = frozenset({"exact", "iexact", "in"})


@dataclass
class OperandReport:
    """What a model's coded values look like against the questionnaire."""

    errors: list[str] = dc_field(default_factory=list)
    unresolved: list[str] = dc_field(default_factory=list)

    def __bool__(self) -> bool:  # truthy when something is wrong
        return bool(self.errors or self.unresolved)


def _question_index() -> dict[str, list]:
    """Canonical field (and its declared payload aliases) -> questions.

    `payload_aliases` is part of the same canonical record — one question
    reached by several payload keys — so a PMT path spelled with an alias
    resolves to the same question and the same list. Using it is reading
    the contract, not widening it.
    """
    from apps.intake.models import FormQuestion

    index: dict[str, list] = {}
    questions = (
        FormQuestion.objects
        .exclude(canonical_field="")
        .select_related("choice_list_ref")
    )
    for question in questions:
        keys = [question.canonical_field, *(question.payload_aliases or [])]
        for key in keys:
            if key:
                index.setdefault(str(key), []).append(question)
    return index


def _active_codes(choice_list) -> set[str]:
    from apps.reference_data.models import ChoiceOption

    return set(
        ChoiceOption.objects
        .filter(choice_list=choice_list, status=ChoiceOption.Status.ACTIVE)
        .values_list("code", flat=True),
    )


def _as_values(operand) -> list[str]:
    if operand is None or operand == "":
        return []
    values = operand if isinstance(operand, (list, tuple, set)) else [operand]
    return [str(v) for v in values if v is not None and v != ""]


def _coded_sites(feature: dict) -> list[tuple[str, list[str], str]]:
    """Every (field, values, where) in one feature that names codes.

    Two shapes carry them. A path feature puts them in `operand`
    (`membership`, `equality`, `inequality`). A collection feature puts
    them in `filter`, keyed by ORM lookup.
    """
    sites: list[tuple[str, list[str], str]] = []

    path = feature.get("path")
    if path:
        values = _as_values(feature.get("operand"))
        if values:
            sites.append((str(path).split(".")[-1], values, "operand"))

    for key, raw in (feature.get("filter") or {}).items():
        name, _, lookup = str(key).partition("__")
        if (lookup or "exact") in _CODE_LOOKUPS:
            values = _as_values(raw)
            if values:
                sites.append((name, values, f"filter[{key}]"))

    return sites


def report_for_variables(variables) -> OperandReport:
    """Check every coded value in `variables` against the questionnaire."""
    report = OperandReport()
    if not variables:
        return report

    index = _question_index()
    code_cache: dict[str, set[str]] = {}

    for entry in variables:
        if not isinstance(entry, dict):
            continue
        feature = entry.get("feature")
        if not isinstance(feature, dict):
            # The legacy {"variable", "weight", "transform"} shape names
            # no codes, so there is nothing here to contradict.
            continue
        name = entry.get("name") or feature.get("path") or "<unnamed>"

        for field_name, values, where in _coded_sites(feature):
            questions = index.get(field_name)
            if not questions:
                report.unresolved.append(
                    f"{name}.{where}: no FormQuestion has canonical_field or "
                    f"payload_alias {field_name!r}, so its codes cannot be "
                    f"checked against a choice list",
                )
                continue

            coded = [q for q in questions if q.choice_list_ref_id]
            if not coded:
                # Resolved, and the question is not a coded field.
                continue

            lists = {q.choice_list_ref.list_name for q in coded}
            if len(lists) > 1:
                report.errors.append(
                    f"{name}.{where}: {field_name!r} resolves to questions "
                    f"bound to different choice lists ({', '.join(sorted(lists))}) "
                    f"— the canonical binding is ambiguous",
                )
                continue

            choice_list = coded[0].choice_list_ref
            key = str(choice_list.id)
            if key not in code_cache:
                code_cache[key] = _active_codes(choice_list)
            active = code_cache[key]

            missing = [v for v in values if v not in active]
            if missing:
                sample = ", ".join(sorted(active)[:6])
                report.errors.append(
                    f"{name}.{where}: {', '.join(repr(m) for m in missing)} "
                    f"{'is' if len(missing) == 1 else 'are'} not an active "
                    f"option on {choice_list.list_name} v{choice_list.version} "
                    f"(question {coded[0].name}); "
                    f"active codes include {sample}"
                    f"{', …' if len(active) > 6 else ''}",
                )

    return report
