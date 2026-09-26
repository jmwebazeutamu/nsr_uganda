# ADR-0041 — A PMT variable's codes come from the canonical question record

- **Status**: Accepted
- **Date**: 2026-09-27
- **Supersedes**: none
- **Related**: ADR-0010 (ChoiceList as the code authority), SAD §4.7,
  SAD open item O-03 (PMT formula), `docs/ssot_register.md`

## Context

A PMT variable scores a coded field by naming the codes inline:

```json
{"name": "head_edu_tertiary", "weight": 0.312,
 "feature": {"path": "head_member.education.highest_grade",
             "type": "membership", "operand": ["17", "…", "23"]}}
```

Nothing connected those strings to the code list they are drawn from.
`PMTModelVersion.variables` is a `JSONField`; there is no foreign key,
no `list_name`, and `feature_evaluator.validate_feature` is a static
JSON check that never touches the database. It validates that a feature
*type* is known and its required keys are present — never that its codes
exist.

The failure mode is silence. `_h_membership` returns `0.0` when nothing
matches. A wrong code is therefore not an error, not a warning, and not
a log line: it is a variable that scores zero for every household in the
country, indefinitely, while the dashboard renders normally and the
model reports as active.

This is not hypothetical. Measured on dev against the seeded v1:

| Variable | Operand | `education_level` spelling |
|---|---|---|
| `head_edu_completed_primary` | `4`, `8`, `17`–`23` | `04` = P1, `08` = P5 |
| `head_edu_secondary` | `8`, `17`–`23` | `08` = P5 |
| `head_edu_tertiary` | `17`–`23` | correct |

The codes are zero-padded in the list and unpadded in the model, so `4`
and `8` match nothing. All three variables collapse onto the same
population and fired on exactly 215 of 374 households — identical counts,
which is the visible symptom of a cumulative ladder that has lost its
lower rungs. Of 1,374 graded `Education` rows, **233 heads at P7 or
S1–S6 score zero on all three education terms**: a household head who
finished secondary school is scored as having no education, and two
weights (0.099 and 0.154) never apply. PMT scores drive eligibility for
social assistance, so this is a targeting error, not a display bug.

A second vocabulary made the problem hard to see. Asked which list owns
a field, `data_management.choice_field_map` and `FormQuestion` give
different answers:

| `canonical_field` | `FormQuestion.choice_list_ref` | `choice_field_map` |
|---|---|---|
| `highest_grade` | `education_level` | `highest_grade` |
| `lighting_energy` | `lighting_source` | `lighting_energy` |
| `drinking_water_source` | `water_source` | `drinking_water_source` |
| `toilet_facility` | `toilet_type` | `toilet_facility` |
| `tenure` | `tenure` | `dwelling_tenure` |

Validating against `choice_field_map` reports 8 of 15 coded variables as
broken. Validating against the questionnaire reports 2. The second
number is the true one, and reaching it required picking an authority.

## Decision

**A PMT variable's codes are validated against the canonical question
record, and a model naming codes the questionnaire does not carry cannot
be activated.**

The chain is the one `docs/ssot_register.md` already names:

```
feature.path leaf ─▶ FormQuestion.canonical_field (or payload_aliases)
                        └─ choice_list_ref ─▶ ChoiceList ─▶ ChoiceOption
```

`apps/pmt/coded_operands.py` resolves it and returns a report.
`services.activate_model_version` raises `PMTApprovalError` on errors,
alongside the existing dual-approval and band-policy checks.

Four choices inside that, each deliberate:

1. **`FormQuestion` is the authority, and `choice_field_map` is not
   consulted at all.** Where they disagree the questionnaire wins,
   because it is what the instrument actually collected. Reading both
   and preferring one would leave the disagreement in place with a
   tiebreak on top; reading only the register's named source is what
   makes the second map's drift a separate, visible bug.

2. **`payload_aliases` counts as part of the record.** One question is
   reachable through several payload keys by design (the Kobo connector
   emits `rooms_sleeping`, the wizard `sleeping_rooms`). Following an
   alias reads the contract; it does not widen it.

3. **Only `ACTIVE` options count.** A deprecated option stays readable
   so historical records remain interpretable — that is ADR-0010's
   promise — but it is not something a *new* model may score on.

4. **An unresolved binding is reported, never fatal.** Collection
   features filter on ORM field names (`asset_type__in`) rather than
   canonical fields, and the asset question's `canonical_field` is
   `assets_owned`, so that binding genuinely does not exist yet.
   Blocking would stop every model activating until the questionnaire is
   extended; inferring the list from elsewhere is the defect above.
   Reporting it is the standing rule for a missing contract.

Codes in the model are still codes, not labels, and no weight, cutoff or
operand is changed by this ADR.

## Consequences

**The existing v1 model is left as it is.** It was activated by
migration `pmt.0006`, not through the service, so it is untouched and
production keeps scoring. Correcting its operands — to
`completed_primary = ["10".."23"]` and `secondary = ["11".."23"]` under
this list — sets eligibility policy and belongs to MGLSD under SAD open
item O-03, not to this ADR. What changes is that the *next* activation
cannot repeat the mistake.

**The gate is only as strong as the record it reads, and today that
record is not everywhere.** `FormQuestion` is populated by
`manage.py load_instrument`, not by a migration, so the test database
has zero questions and every coded value there reports as unresolved
rather than checked. `test_the_gate_is_inert_without_the_questionnaire`
pins that fact so it cannot be mistaken for the gate passing. **This is
the main open risk in this decision**: an environment built from schema
alone gets a validation that approves everything. Seeding the instrument
as part of environment setup is what closes it, and is the recommended
follow-up.

**Validation reaches the database, which `validate_feature` does not.**
The two are kept separate on purpose: the static check stays usable in
the Rule Editor without a query, and the code check runs at the
activation gate where one query per list is cheap and correctness
matters more than latency.

**`choice_field_map` is now known to disagree with the questionnaire in
at least five places.** This ADR does not fix it — PMT no longer depends
on it — but that map still drives payload label rendering, so the
disagreement has consequences elsewhere and should be reconciled against
`FormQuestion` in its own change.

## Alternatives considered

**Put a `choice_list` FK on each variable.** Strongest coupling, but it
would let a model name a list the question disagrees with — a third
vocabulary, and the problem again one level up. The question already
knows its list; asking it is better than restating the answer.

**Validate at score time.** Too late and too noisy: the model is already
live, the households are already scored, and the error arrives once per
household per night rather than once, at the gate, where someone is
looking.

**Normalise codes on comparison (zero-pad, casefold).** This is the
shape of instance 9 in the two-vocabularies record, where `412.02` and
`412.2` are both real and different places. Padding `"4"` to `"04"` would
have silently turned "completed primary" into "P1" and produced a
confidently wrong score instead of an obviously zero one. Resolve
against the list; never transform to force a match.

**Block on unresolved bindings.** Strictly safer and operationally
unusable — no model could activate until every ORM filter field has a
canonical question. Deferred to the follow-up that seeds the instrument.
