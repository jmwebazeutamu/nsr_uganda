"""The field dictionary the review screens read instead of their own maps.

One question this answers, for any canonical payload field: what is this
called, and if it holds a code, which ChoiceList decodes it?

The answers come from the active FormVersion — `FormQuestion.label` and
`FormQuestion.choice_list_ref` — so the screen and the instrument cannot
say different things about the same field. Where the registry has no
answer the dictionary says so, by name, rather than deriving a plausible
label from the key. A field nobody has mapped is a schema gap someone has
to close; a humanised key hides it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from apps.dqa.models import DqaRule, RuleStatus

from .canonical_fields import CAPTURE_METADATA
from .models import FormQuestion, FormVersion

# Age thresholds the household composition summary needs, and the rule
# parameter each one is read from. The composition panel used to carry
# 12/18/60 as literals; two of the three are policy already recorded in
# DQA rule parameters, so they are read from there and change when the
# rule changes.
THRESHOLD_SOURCES = {
    "head_min_age": ("AC-HOH-AGE", "min_head_age"),
    "child_max_age": ("AC-HOH-AGE-CHILD-LED", "max_age_inclusive"),
    "orphan_max_age": ("AC-ORPHAN-FLAG", "max_age"),
}

# The elderly boundary has no owner.
#
# `AC-HOH-AGE-CHILD-LED` and `AC-ORPHAN-FLAG` define the child boundary,
# but nothing in the registry defines where "elderly" starts — no DQA
# rule carries it, no choice list encodes it, and there is no system
# configuration store to hold it. The composition panel used 60 as a
# literal, which is a plausible number with no authority behind it.
#
# Rather than move that literal somewhere more respectable, the
# dictionary reports it as an unresolved dependency: the API returns
# null, the screen omits the elderly band and names the parameter that
# would restore it. See the missing_dependencies contract test.
UNRESOLVED_THRESHOLDS = {
    "elderly_min_age": (
        "No DQA rule or configuration entry defines where 'elderly' "
        "begins. The composition panel previously assumed 60. Define it "
        "as a rule parameter (for example AC-ELDERLY-HEAD.min_age) and "
        "the elderly band returns automatically."
    ),
}


# The instrument prefixes every label with its position on the form
# ("G6. Main wall material", "A11/A12. CAPI GPS Coordinates", "L01.a
# Engage in casual labor"). That prefix is how an enumerator finds the
# question on paper; on screen it is noise in front of every row. It is
# stripped for display only — `question_label` keeps the original and
# `question_name` keeps the code, so a reviewer can still trace a row
# back to the paper form.
_QUESTION_CODE_PREFIX = re.compile(r"^[A-Z]+\d+(?:/[A-Z]+\d+)?\.(?:\s*[a-z]\b)?\s*")


def strip_question_code(label: str) -> str:
    stripped = _QUESTION_CODE_PREFIX.sub("", label or "").strip()
    # Never return an empty label: a question whose text is only its code
    # would otherwise render as a blank row.
    return stripped or (label or "").strip()


@dataclass
class FieldEntry:
    label: str
    question_label: str = ""
    choice_list: str | None = None
    question_name: str = ""
    section: str = ""
    type: str = ""
    source: str = "instrument"

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "question_label": self.question_label or self.label,
            "choice_list": self.choice_list,
            "question_name": self.question_name,
            "section": self.section,
            "type": self.type,
            "source": self.source,
        }


@dataclass
class FieldDictionary:
    fields: dict[str, FieldEntry] = dc_field(default_factory=dict)
    thresholds: dict[str, int | None] = dc_field(default_factory=dict)
    missing_thresholds: dict[str, str] = dc_field(default_factory=dict)
    form_version: int | None = None
    form_name: str = ""
    conflicts: list[dict] = dc_field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "form_version": self.form_version,
            "form_name": self.form_name,
            "fields": {k: v.as_dict() for k, v in sorted(self.fields.items())},
            "thresholds": self.thresholds,
            "missing_thresholds": self.missing_thresholds,
            "conflicts": self.conflicts,
        }


def _active_rule_parameters(rule_id: str) -> dict:
    rule = (
        DqaRule.objects.filter(rule_id=rule_id, status=RuleStatus.ACTIVE)
        .order_by("-version")
        .first()
    )
    return (rule.parameters or {}) if rule else {}


def build_field_dictionary(form_version: FormVersion | None = None) -> FieldDictionary:
    """Build the dictionary for `form_version`, defaulting to the active one."""
    if form_version is None:
        form_version = FormVersion.objects.filter(is_active=True).first()

    dictionary = FieldDictionary()
    if form_version is not None:
        dictionary.form_version = form_version.version
        dictionary.form_name = form_version.name

        questions = (
            FormQuestion.objects
            .filter(section__form_version=form_version)
            .exclude(canonical_field="")
            .select_related("section", "choice_list_ref")
            .order_by("section__order", "order_in_section")
        )
        for question in questions:
            canonical = question.canonical_field
            choice_list = getattr(question.choice_list_ref, "list_name", None)
            entry = FieldEntry(
                label=strip_question_code(question.label),
                question_label=question.label,
                choice_list=choice_list,
                question_name=question.name,
                section=question.section.code,
                type=question.type,
            )
            existing = dictionary.fields.get(canonical)
            if existing is None:
                dictionary.fields[canonical] = entry
                continue
            # Several questions feeding one canonical column is expected
            # in repeat blocks (the K03 shock-type set). Them disagreeing
            # about the choice list is not — that is the drift this whole
            # exercise exists to surface, so it is reported rather than
            # silently resolved by load order.
            if existing.choice_list != entry.choice_list:
                dictionary.conflicts.append({
                    "canonical_field": canonical,
                    "kept": existing.question_name,
                    "ignored": question.name,
                    "reason": (
                        f"choice list differs: {existing.choice_list!r} "
                        f"vs {entry.choice_list!r}"
                    ),
                })

    # Capture metadata: emitted by the channel, never asked of a
    # respondent, so no FormQuestion owns it. Declared once, server-side.
    for name, label in CAPTURE_METADATA.items():
        dictionary.fields.setdefault(
            name, FieldEntry(label=label, source="capture-metadata"),
        )

    for key, (rule_id, parameter) in THRESHOLD_SOURCES.items():
        dictionary.thresholds[key] = _active_rule_parameters(rule_id).get(parameter)
    for key, why in UNRESOLVED_THRESHOLDS.items():
        dictionary.thresholds[key] = None
        dictionary.missing_thresholds[key] = why

    return dictionary
