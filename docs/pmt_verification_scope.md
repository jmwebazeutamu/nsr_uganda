# PMT Run Verification & Per-Household Explanation — Scope

**Status:** Draft for review
**Date:** 2026-09-28
**Author:** Implementation lead, with architecture review
**Related:** ADR-0025 (feature DSL), ADR-0029 (audit chain append), ADR-0041
(PMT codes come from the questionnaire), SAD §4.7, SAD open item O-03

---

## 1. Summary

PMT scores decide who is considered for social assistance. Today a score
can be wrong in a way that raises no error, writes no warning, and looks
identical to a correct one: `_h_membership` returns `0.0` when no code
matches, so a variable naming a code the registry does not carry scores
zero for every household in the country, forever, while the dashboard
renders normally.

That is not hypothetical. The ACTIVE v1 model asks `education_level` for
`"4"` and `"8"`; that list spells them `"04"` (P1) and `"08"` (P5). Both
match nothing, so `head_edu_completed_primary` and `head_edu_secondary`
collapse onto `head_edu_tertiary` — all three fire on exactly the same
215 of 374 dev households. **233 of 1,374 graded Education rows are
household heads at P7 or S1–S6 being scored as having no education at
all**, with three weights (0.099, 0.154, 0.312) that should stack never
applying.

This scope covers the ability to run PMT in an explained mode, to see
per household how a score was computed, and to export that as auditable
evidence. Its single most important output is not the export — it is the
ability to distinguish **"scored zero because the data is missing"** from
**"scored zero because the code never matches"** from **"scored zero
because the weight is zero"**.

**Recommendation:** do not build a population-wide `log=True` dump. At 12
million households that artefact is 40–60 GB of personal data that nobody
will read. Build one server-side explainer and serve it three ways: an
explain flag on the existing engine, an aggregate variable-health report
containing no personal data, and a per-household projection served
interactively or as a bounded, sampled, hash-bound artefact.

---

## 2. In scope

1. An **explain mode** on the existing compute path — not a second
   scoring implementation.
2. A **per-variable cause classification** for every zero contribution.
3. A **per-household explanation**, served interactively (scope-filtered,
   audited) and as a bounded export artefact.
4. A **population variable-health report** — per variable, its weight and
   its fire rate, with no personal data.
5. A **verification run** that can be pointed at a DRAFT model, so a
   defect is caught *before* activation rather than after.
6. **Formula pinning** so "re-run this and prove the same number" is
   answerable.

## 3. Out of scope

- **A full national per-household export.** See §9.
- **Per-household `AuditEvent` rows for a batch run.** See §8.
- **Correcting v1's operands.** v2 exists as a DRAFT precisely because
  changing a scored operand is an eligibility-policy change requiring
  MGLSD sign-off (O-03). This feature makes the defect undeniable; it
  does not fix it quietly.
- **A subject-facing explanation** for the household themselves. Likely
  required under DPPA 2019 — see §11 Q2 — but it is a different design
  and needs a decision first.
- **Recalibrating the model.** See §11 Q1.

---

## 4. Findings this scope rests on

Each was verified against the code, not assumed.

| # | Finding | Evidence |
|---|---|---|
| F1 | **Two snapshot vocabularies already exist.** `engine._compute` writes `{value, weight, contribution, feature_type}` for a DSL row and `{raw, transformed, weight, contribution}` for a legacy row. Stored `PMTResult`s carry both depending on which model scored them. | `apps/pmt/engine.py` |
| F2 | **A third implementation of scoring exists.** `admin_console.api.simulate` re-implements the accumulation loop with its own result shape. `snapshots._refresh_variable_influence` open-codes a `value ?? transformed` fallback. | `apps/admin_console/api.py:737`, `apps/admin_console/snapshots.py` |
| F3 | **`resolve_path` short-circuits on the first missing segment** and records nothing about which one broke. A missing `Dwelling` row and a blank `floor_material` are indistinguishable downstream. | `apps/pmt/feature_evaluator.py` |
| F4 | **An ACTIVE model's formula is editable with no sign-off and no audit row.** `PMTModelVersionAdmin.readonly_fields` is only `(id, created_at, updated_at, approved_at)`; `variables`, `intercept` and `band_cutoffs` are editable and there is no status guard. A `PMTResult`'s FK therefore pins *the row*, not *the formula*. **Reproducibility is currently unprovable.** | `apps/pmt/admin.py` |
| F5 | **Detail-entity history is not written in production.** `DwellingVersion`, `EducationVersion`, `UtilitiesVersion` have **zero** production writers; only `HouseholdVersion` and `MemberVersion` have one each. 13 of v1's 25 variables read entities with no version history. | `apps/data_management/models.py`, `apps/update_workflow/services.py` |
| F6 | **`PMTRun` is a phantom.** Named in `apps/pmt/constants.py:17`; no such model exists. The real run row is `PMTRecomputeJobRun`. | `apps/pmt/constants.py` |
| F7 | **The audit chain is a hard serialization point.** Every `AuditEvent` insert takes a row lock on a single `AuditChainHead`. Per-household audit for a 12M sweep is infeasible, not merely noisy. | ADR-0029 |
| F8 | **`IsAdminConsoleUser` is not a geographic scope.** It gates on group membership only. Correct today (those endpoints serve aggregates); fatal if a per-household export is added there without `scope_q_for_field`. | `apps/admin_console/permissions.py` |

**F5 is the decisive architectural constraint.** Because how a household
looked at scoring time cannot be reconstructed, the explanation must
record *what the engine observed*, not re-resolve the path later. Those
answer different questions.

**F4 is the most urgent defect** and is independent of everything else
here.

---

## 5. Design

### 5.1 Explain mode

`_compute(household, model_version, *, band: bool, explain: bool = False)`.
With `explain=False` the behaviour is byte-for-byte what it is today —
pinned by a test. With `explain=True`, two keys are added per entry and
nothing else:

```jsonc
"highest_grade__secondary": {
  "value": 0.0, "weight": 0.154, "contribution": 0.0,  // unchanged
  "feature_type": "membership",                         // unchanged
  "observed": "08",   // NEW — what the engine actually read at feature.path
  "missing": ""       // NEW — deepest segment that resolved to None; "" if the leaf resolved
}
```

`observed` and `missing` name concepts nothing in the codebase names
today, so they are additions, not aliases. `operand`, `path` and the
weight are **not** copied in: they live on `PMTModelVersion.variables`,
which is the SSOT for the formula, and `PMTResult.model_version` pins the
row. Keeping them out stops the snapshot doubling in size and becoming a
second statement of the model.

### 5.2 One explainer, one vocabulary

New module `apps/pmt/explain.py` — the only new file with logic. It owns
the cause classifier, the legacy/DSL normaliser, the `explain_result()`
projection and the row renderer.

Going forward the writer vocabulary is **the DSL spelling**.
`raw`/`transformed` are frozen as the legacy-path spelling, never written
for a DSL row and **never renamed on existing rows** — they are
audit-bearing and immutable. `normalise_entry()` becomes the *sole*
reader of both.

Consequently **`simulate` and `_refresh_variable_influence` are
refactored onto the shared explainer** and their private implementations
deleted (F2). This feature should end with one implementation of scoring,
not four.

### 5.3 The explanation is a projection, not a table

`explain_result(result)` joins `PMTResult.inputs_snapshot` ×
`model_version.variables` × the as-of `PMTBandThreshold` basis ×
`ChoiceOption` labels. Nothing is persisted. For a hypothetical run
against a DRAFT model with no `PMTResult`, the same function takes the
in-memory `(score, snapshot)` the engine just produced — one code path,
two sources.

**No `PMTExplanation` table.** It would be parallel to `PMTResult`, about
300M rows nationally, and every byte is derivable.

---

## 6. Making silent zeros visible — the core requirement

One server-side classifier. Status codes come from a seeded
`pmt_variable_status` ChoiceList with canonical codes in
`apps/pmt/constants.py`, following the `pmt_trigger_source` precedent.
The console renders the code's label and its `ui_tone` and decides
nothing.

| status | meaning | determined by |
|---|---|---|
| `contributing` | the variable moved the score | `value != 0 and weight != 0` |
| `zero_weight` | cannot move the score whatever the data says | `weight == 0` on the pinned version |
| `missing_data` | the entity the path needs does not exist | `missing != ""`, naming the segment |
| `no_value` | the entity exists, the answer is blank | path resolved, `observed` empty |
| `code_no_match` | the household's code is valid but outside this operand | active `ChoiceOption`, not in `operand` |
| `operand_not_in_choice_list` | **the model names codes the questionnaire does not carry** | `apps.pmt.coded_operands`, per household |
| `genuine_zero` | the test legitimately failed | value 0, operand valid, data present |
| `binding_unresolved` | no `FormQuestion` for the field, so no authority for its codes | ADR-0041's unresolved set |
| `error` | the evaluator raised | existing `error` key, surfaced not folded into a zero |

Two distinctions carry the whole feature:

- **`code_no_match` vs `operand_not_in_choice_list`** — the first says
  *this head has no secondary education*; the second says *this variable
  can never fire for anyone*. v1's `"4"`/`"8"` lands in the second bucket
  for every household, on every row, with a non-zero weight attached.
- **`missing_data` vs `no_value`** — 13 variables reading absent
  `Dwelling`/`Utilities` rows are not "households with no floor", they
  are "an entity nobody captured".

**The aggregate report is the same classifier counted.** Per variable:
weight, count and share per status, and a **fire rate**. A variable with
a non-zero weight and a fire rate of `0.000` is the alarm. ~25 rows, no
personal data. This is the artefact to put in front of MGLSD.

---

## 7. The verification run

`log=True` is an explain flag, not a new pipeline.

**Command** `apps/pmt/management/commands/pmt_verify.py`, following the
read-only reporter convention of `report_unmapped_codes`:

| flag | notes |
|---|---|
| `--model-version N` | required; **may be a DRAFT** — verifying v2 before activation is the point |
| `--household` / `--sub-region` / `--district` | codes validated against `GeographicUnit`; never a name |
| `--sample N` / `--stratify-by` / `--all` | `--all` refused above the configured cap |
| `--actor <username>` | required; the run is scoped and audited **as that operator**, so the CLI is not a back door around ABAC |
| `--reproduce` | Phase 3 |
| `--format ndjson\|csv`, `--out` | defaults to the bundle store |

**No `--persist`.** A verification run never writes `PMTResult`. It must
not: a DRAFT percentile model has no `PMTBandThreshold` rows, so
`derive_band` raises and `PMTResult.band` is non-null. Verification uses
score-only semantics when the model cannot band, and reports that fact
rather than failing.

**Run record: extend `PMTRecomputeJobRun`; do not create `PMTRun`.** Add
`kind` (from a seeded `pmt_run_kind` ChoiceList), `model_version` FK
(nullable), `parameters` JSON (so the run is re-runnable from its own
row), `artefact_sha256`. Fix the phantom reference in `constants.py`.
**Consequential change:** `_job_payload()` and `_recent_events_payload()`
in `admin_console/api.py` must filter by `kind`, or verification runs
will masquerade as threshold runs on the dashboard.

---

## 8. Audit

HANDOFF §4.4 says per-household simulation is not audited because it
"would flood the chain". That is not a valid reason to skip auditing a
read of personal data, and F7 shows the alternative is infeasible rather
than merely noisy. The resolution is to **audit the run and make its
contents provable**:

- one `pmt.verify.run` event per run, `entity_type="pmt_run"`, carrying
  `{model_version, variables_sha256, kind, household_count, scope_filter,
  sample_spec, artefact_sha256}`. The artefact hash inside the
  hash-chained row makes the set of households read tamper-evident
  without 12M rows.
- one `pmt.verify.export.download` event per artefact fetch — a download
  is a fresh read of personal data by a possibly different actor.
- per-household events **only** on the interactive single-household
  explain, which rides the existing `AuditReadMixin` on
  `PMTResultViewSet` (`access_purpose="ELIGIBILITY"` already declared).
  No new audit plumbing.
- `emit` is the only writer. No `AuditEvent.objects.create` anywhere.

Separately: `simulate` genuinely needs no audit, but for a stronger
reason than §4.4 gives — it evaluates a caller-supplied feature dict and
touches no personal data. Correct that comment.

---

## 9. The export, and scale

**Formats.** NDJSON primary (matches `apps/data_requests/bundles.py`,
streams, one line per household). CSV secondary in **long** form, one row
per household × variable — a wide CSV of 25 variables × 5 columns is
unreadable and breaks the moment the model changes. No XLSX.

**Endpoints.**
- `GET /api/v1/pmt/results/{id}/explain/` — a detail action on the
  existing `PMTResultViewSet`, which already has `AuditReadMixin`,
  `ScopedQuerysetMixin` and a declared access purpose. That inheritance
  is the strongest argument for putting it there rather than in
  `admin_console` (F8).
- `POST /api/v1/admin/pmt/verify/` → `{run_id, artefact_sha256, report_url}`.
- `GET /api/v1/admin/pmt/verify/runs/{id}/artefact/` — streams the bytes.

**Scope.** `scope_q_for_field(user, "household__sub_region_code")` — the
path `PMTResultViewSet` already declares. Admin-group membership is
**not** national scope; both checks always apply.

**PII.** No NIN, no `nin_hash`, no `nin_last4`, no names, no GPS, no
phone. The head appears as the role "head", never as a member id. But the
DPIA must be honest: the export **is** personal data — observed education
level, dwelling materials and household size against an identified
`household_id` are exactly that. Guard with a denylist test over every
key and value in a rendered row, driven off model field lists rather than
a hand-typed string list.

**Codes, not labels.** Geography as codes from `Household.GEO_CODE_FIELDS`,
names via the `_labels` projection. Choice labels from `ChoiceOption`:
**code first, label second, never label instead of code.** An export that
writes "Completed P7" instead of `"10"` re-hides the bug.

**Size.** ~3–5 KB per household in NDJSON. 374 households ≈ 1.5 MB.
**12M ≈ 40–60 GB uncompressed.** Enforce a row cap read from
configuration; a missing config value **fails closed naming the key**.

**Feasible:** single-household explain (O(1)); sampled export stratified
by sub-region (a systematically broken variable has fire rate 0 in *any*
sample, so a few thousand households suffices for this bug class);
aggregate variable-health as part of the nightly sweep, chunked per
sub-region (the tables are partitioned by sub-region per ADR-0005, so
that pass is partition-local).

**Not feasible — do not build:** full national per-household export;
per-household audit for a sweep (F7); on-demand national aggregate
reading 12M `inputs_snapshot` blobs inside a request.

**Two pre-existing scale bombs nearby** — flag, do not fix here:
`_refresh_variable_influence` loads *every* `PMTResult.inputs_snapshot`
into Python; `_bootstrap_scores` scores every household in a Python loop
inside one atomic block.

---

## 10. Reproducibility

Three gaps, in order of importance.

**G1 — the formula is not pinned. Fix it.** Add
`PMTModelVersion.variables_sha256` (sha256 over a canonical
`json.dumps(..., sort_keys=True)`) and copy it to a new
`PMTResult.variables_sha256` at compute time. Two consequences worth
taking: it gives a real immutability guard (set `variables`, `intercept`,
`band_cutoffs` readonly for non-DRAFT rows — F4); and **do not backfill**
existing results, because we do not know what the formula was. Null means
"unknown, predates pinning" and the output must say so rather than imply
a reproducibility it cannot offer.

**G2 — the band basis is reconstructable; derive it, do not store it.**
`band_basis(result)` = latest `PMTBandThreshold` per band with
`computed_at <= result.computed_at`. Exact, because the table is
append-only and each recompute is atomic per model. This answers "the
percentile thresholds move daily": the explanation states the score, the
thresholds *as they stood*, the distance to the nearest boundary, and —
separately — where the score would land under today's thresholds. Those
differing is not a bug, and the output says which is which.

**G3 — household state as-of a past score is not reconstructable (F5).**
Accept it, and be explicit in the output. This is why `observed` is
stored rather than re-resolved.

**`--reproduce` reports exactly one of four outcomes, all useful:**

| outcome | meaning |
|---|---|
| `reproduced` | same score at 4 dp |
| `formula_changed` | `variables_sha256` differs — reported from the hash, not inferred from a score mismatch |
| `inputs_changed` | formula identical, `observed` values differ, **and it names which variables moved** — a recompute signal, not a defect |
| `not_reproducible` | hash null (predates pinning) |

**Float caveat, stated not chased:** the score accumulates float
contributions in list order into a `Decimal(8,4)` column, so reordering
variables can move the last decimal. Compare at stored precision;
document it; do not pursue bit-exactness.

---

## 11. Open questions — MGLSD / DPO

1. **Are v1's weights still valid once the operands are corrected?** They
   were fitted against the operands *as intended*, not *as spelled*. If
   not, v2 needs recalibration by UBOS, not just a code fix. **Engineering
   cannot answer this.** Blocks activation of v2.
2. **Is a per-household explanation disclosable to the household?** DPPA
   2019 access rights plus an automated eligibility decision make this
   the likeliest GRM request in the system. If yes, a subject-facing
   variant is needed — labels, plain language, and a decision on whether
   weights are disclosed — and that changes the design materially. **Ask
   before building.**
3. **Retention period for verification artefacts** in bundle storage.
   Personal data at rest; the DPO sets the period. No default will be
   picked.
4. **Which admin-console groups may run a verification export**, and does
   `mglsd_statistics` carry national ABAC scope? Group membership and
   geographic scope are independent today, and this scope requires both.
5. **Should a zero-fire-rate, non-zero-weight variable block
   activation?** That extends ADR-0041's gate from "the codes exist" to
   "the codes actually fire on the population". It is the strongest
   version of what was asked for — and it is an eligibility-policy gate,
   not a technical one.
6. **What is the remediation for scores computed under v1** while the
   education defect was live?

---

## 12. ADR

**ADR-0042 — A PMT score explains itself, in one vocabulary.**

- **D1.** The snapshot vocabulary is the DSL spelling plus `observed` and
  `missing`. `raw`/`transformed` are frozen as the legacy spelling; one
  normaliser is the sole reader of both; `simulate` and
  `_refresh_variable_influence` are refactored onto it.
- **D2.** The explanation is a projection of snapshot × model version ×
  as-of thresholds. There is no explanation table.
- **D3.** A zero contribution is classified by cause, and
  `operand_not_in_choice_list` is a *model* defect on ADR-0041's
  authority — distinct from a household that legitimately scores zero.
- **D4.** A batch run is audited once, at the run, with the artefact
  sha256 inside the hash-chained row. Per-household audit is reserved for
  interactive reads. ADR-0029 is why.
- **D5.** `variables_sha256` pins the formula; non-DRAFT variables become
  admin-readonly; `PMTRecomputeJobRun` gains `kind` and is the single run
  record, retiring the phantom `PMTRun`.

---

## 13. Tests

New `apps/pmt/test_explain.py`:

- `test_a_code_the_choice_list_does_not_carry_is_reported_as_an_operand_defect`
  — v1's exact education variable against a head with `highest_grade="08"`.
  Asserts `operand_not_in_choice_list`, **not** `genuine_zero`.
- `test_a_missing_detail_row_is_missing_data_not_a_zero` — asserts
  `missing == "dwelling"`.
- `test_a_blank_answer_is_no_value_not_missing_data`.
- `test_a_zero_weight_variable_is_never_reported_as_a_data_problem`.
- `test_explain_mode_does_not_change_the_score` — the regression
  protecting every existing and future score.
- `test_the_legacy_snapshot_vocabulary_normalises_to_the_same_explanation`.
- `test_the_writer_emits_no_fourth_vocabulary` — asserts the exact
  allowed key set. The guard this project specifically needs.

New `apps/pmt/test_verify_run.py`:

- `test_a_verification_run_emits_one_audit_event_not_one_per_household`.
- `test_a_verification_run_writes_no_pmt_result`.
- `test_a_draft_model_can_be_verified_without_activation` — the
  acceptance test for "would have caught the education bug before
  activation".
- `test_the_run_is_scope_filtered`.
- `test_the_export_never_contains_a_nin_or_a_name`.
- `test_a_missing_cap_configuration_fails_closed_and_names_the_key`.
- `test_the_artefact_sha256_in_the_audit_row_matches_the_stored_bytes`.

New `apps/pmt/test_reproducibility.py`:

- `test_a_changed_formula_is_reported_from_the_hash_not_the_score`.
- `test_the_band_basis_is_reconstructed_as_of_the_result_not_as_of_today`.
- `test_a_changed_household_is_reported_as_inputs_changed_and_names_the_variable`.

Every test above is verified by removing the behaviour it covers and
confirming it fails.

**Existing test to respect, not edit:**
`tests/integration/test_us_s22_de_e2e.py` asserts `"raw" in entry and
"transformed" in entry` for the legacy v22001 model. It must keep passing
**unchanged** — it is the accidental guard proving the legacy keys were
not renamed.

**Definition of Done gaps:** `docs/openapi/pmt.yaml` does not exist and
must be created for the new endpoints, with a contract test. A DPIA note
is required under the existing per-sprint convention.

---

## 14. Sequencing

| Phase | Content | Size |
|---|---|---|
| **0** | Fire-rate alarm off existing `PMTVariableInfluence` data, on the PMT dashboard and in `pmt_recompute_run_report`. **No migration, no new module.** | half a day |
| **1** | `explain.py`, `observed`/`missing`, the normaliser, refactor `simulate` + `_refresh_variable_influence`, single-household explain action | ~1 sprint week |
| **2** | `pmt_verify` command, `PMTRecomputeJobRun` extensions, run audit, NDJSON/CSV artefact, scoped streaming endpoint, `docs/openapi/pmt.yaml`, DPIA note | ~1 sprint week |
| **3** | `variables_sha256`, admin immutability guard (F4), `--reproduce`, as-of band basis | ~3 days |
| **4** | Population variable-health folded into the nightly sweep, chunked per sub-region | ~3 days |

**Phase 0 is worth doing first and separately.** `_refresh_variable_influence`
already computes `sample_mean` per variable nightly, and the dashboard
already renders it. A membership variable that never matches has
`sample_mean == 0.0000` exactly. Flagging any variable with `weight != 0`
and `sample_mean == 0` over a configured minimum sample raises the alarm
on the exact defect found, from data already being computed. It cannot
say *why* — that is Phase 1 — but it closes the blind spot immediately.

**F4 (admin immutability) is independent of all of this** and should be
lifted out of Phase 3 if it is not being scheduled soon.
