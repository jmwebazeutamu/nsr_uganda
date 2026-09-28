"""Findings about a PMT model's variables, computed server-side.

A PMT variable can be broken in a way that raises nothing. A membership
test whose operand names a code the registry does not carry returns 0.0
for every household — `_h_membership` has no other answer — so the
variable contributes zero forever while the model reports as active and
the dashboard renders normally. That is how the live v1 model came to
score 233 household heads at P7 or secondary level as having no
education at all.

The dashboard could not show it. `_variables_top_payload` returns the
ten variables with the highest `influence`, and a variable that never
fires has influence exactly 0 — so the one view that would reveal the
defect is the one view structurally guaranteed to exclude it. A finding
has to scan every variable, not the interesting ones.

What this is not
----------------
It is not an explanation of *why* a variable failed: distinguishing
"the entity is missing" from "the code never matches" from "the answer
was blank" needs what the engine observed per household, which is Phase
1 of `docs/pmt_verification_scope.md`. This says only that a variable
carrying weight has never once moved a score, which is enough to raise
the alarm and is answerable from data already collected nightly.

Vocabulary
----------
Finding codes are `pmt_variable_finding` ChoiceList codes and tones are
`ui_tone` codes, resolved server-side so the console renders a label and
a tone and decides neither. `_FINDING_TONE` below is the only place PMT
code translates a finding to a tone, mirroring the single translation
table in `apps.partners.services.activity`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

#: `pmt_variable_finding` ChoiceList codes. Seeded by
#: reference_data migration 0024; `test_finding_codes_are_seeded` pins
#: these constants against the list so a rename cannot drift.
FINDING_NEVER_FIRES = "never_fires"
FINDING_INSUFFICIENT_SAMPLE = "insufficient_sample"
FINDING_OPERAND_NOT_IN_CHOICE_LIST = "operand_not_in_choice_list"

#: finding code -> `ui_tone` code.
_FINDING_TONE: dict[str, str] = {
    FINDING_NEVER_FIRES: "danger",
    FINDING_INSUFFICIENT_SAMPLE: "neutral",
    FINDING_OPERAND_NOT_IN_CHOICE_LIST: "danger",
}


def minimum_sample() -> int:
    """How many scored households a variable must have been read from
    before "it never fires" is worth acting on.

    Configuration, not a literal: a national sweep and a pilot district
    warrant different thresholds, and neither is an engineering
    decision. `PMT_VARIABLE_FINDING_MIN_SAMPLE`.
    """
    return int(getattr(settings, "PMT_VARIABLE_FINDING_MIN_SAMPLE", 30))


@dataclass(frozen=True)
class VariableFinding:
    """One variable's standing. `code` is "" when nothing is wrong."""

    variable_name: str
    code: str
    weight: float
    fire_rate: float
    sample_size: int
    nonzero_count: int

    @property
    def tone(self) -> str:
        return _FINDING_TONE.get(self.code, "neutral")


def finding_for(influence) -> VariableFinding:
    """Classify one `PMTVariableInfluence` row.

    A variable with no weight is not reported however it behaves: it
    cannot move a score, so whether it fires is not a defect. That is a
    deliberate exclusion rather than an oversight — a draft model full
    of zero-weight placeholders would otherwise raise an alarm on every
    row and teach everyone to ignore the column.
    """
    weight = float(influence.weight or 0)
    sample_size = int(influence.sample_size or 0)
    nonzero = int(influence.nonzero_count or 0)
    fire_rate = (nonzero / sample_size) if sample_size else 0.0

    code = ""
    if weight != 0 and nonzero == 0:
        code = (
            FINDING_NEVER_FIRES if sample_size >= minimum_sample()
            else FINDING_INSUFFICIENT_SAMPLE
        )

    return VariableFinding(
        variable_name=influence.variable_name,
        code=code,
        weight=weight,
        fire_rate=round(fire_rate, 4),
        sample_size=sample_size,
        nonzero_count=nonzero,
    )


def findings_for_model(model_version) -> list[VariableFinding]:
    """Every variable of `model_version`, most serious first.

    Every variable, not the influential ones — see the module docstring.
    Reads the latest influence row per variable name.
    """
    from .models import PMTVariableInfluence

    if model_version is None:
        return []
    latest: dict[str, object] = {}
    rows = (
        PMTVariableInfluence.objects
        .filter(model_version=model_version)
        .order_by("variable_name", "-computed_at")
    )
    for row in rows:
        latest.setdefault(row.variable_name, row)

    findings = [finding_for(row) for row in latest.values()]
    # Reported first, then the widest weight — an unfired variable
    # carrying 0.312 matters more than one carrying 0.038.
    findings.sort(key=lambda f: (f.code == "", -abs(f.weight), f.variable_name))
    return findings


def operand_findings(model_version) -> list[VariableFinding]:
    """Variables whose operands name codes the questionnaire lacks.

    This needs no scored households at all — it compares the model
    against `FormQuestion.choice_list_ref -> ChoiceList -> ChoiceOption`
    through the same gate that refuses activation (ADR-0041), so it
    answers on a registry with no results yet and on a DRAFT.

    It is also the finding that catches the live v1 education defect,
    which `finding_for` cannot: `head_edu_completed_primary` asks for
    "4", "8" and 17-23, and the 17-23 part matches, so the variable DOES
    fire and its `nonzero_count` is not zero. It fires on the wrong
    population — every head is classified by their tertiary status —
    and only a comparison against the code list can see that.
    """
    from .coded_operands import report_for_variables

    if model_version is None:
        return []
    report = report_for_variables(model_version.variables)
    by_weight = {
        (entry.get("name") or ""): float(entry.get("weight") or 0)
        for entry in (model_version.variables or [])
        if isinstance(entry, dict)
    }
    findings = []
    for error in report.errors:
        # `report_for_variables` formats "<name>.<where>: ..." — the
        # variable name is everything before the first dot.
        name = error.split(".", 1)[0]
        findings.append(VariableFinding(
            variable_name=name,
            code=FINDING_OPERAND_NOT_IN_CHOICE_LIST,
            weight=by_weight.get(name, 0.0),
            fire_rate=0.0,
            sample_size=0,
            nonzero_count=0,
        ))
    return findings


def payload_for_model(model_version) -> list[dict]:
    """The findings as the console renders them, codes and tones only."""
    return [
        {
            "variable": f.variable_name,
            "finding": f.code,
            "finding_tone": f.tone,
            "weight": f.weight,
            "fire_rate": f.fire_rate,
            "sample_size": f.sample_size,
            "nonzero_count": f.nonzero_count,
        }
        for f in _all_findings(model_version)
        if f.code
    ]


def _all_findings(model_version) -> list[VariableFinding]:
    """Both kinds, most serious weight first, one row per variable.

    A variable with a broken operand is reported as that and not as
    "never fires": the operand defect is the cause and the more
    actionable statement.
    """
    operand = operand_findings(model_version)
    named = {f.variable_name for f in operand}
    rest = [f for f in findings_for_model(model_version)
            if f.code and f.variable_name not in named]
    combined = operand + rest
    combined.sort(key=lambda f: (-abs(f.weight), f.variable_name))
    return combined
