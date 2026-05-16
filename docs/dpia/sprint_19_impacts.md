# DPIA — Sprint 19 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 19
  (the Questionnaire Authoring epic, US-116 → US-120).
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).
**Previous instalments**:
- `/docs/dpia/sprint_2_3_impacts.md` (Sprints 2-4)
- `/docs/dpia/sprint_5_6_impacts.md` (Sprints 5-6)
- `/docs/dpia/sprint_7_impacts.md` (Sprint 7)
- `/docs/dpia/sprint_8_impacts.md` (Sprint 8)
- `/docs/dpia/sprint_9_impacts.md` (Sprint 9)
- `/docs/dpia/sprint_10_11_impacts.md` (Sprints 10 + 11)
- `/docs/dpia/sprint_12_impacts.md` (Sprint 12)
- `/docs/dpia/sprint_13_impacts.md` (Sprint 13)
- `/docs/dpia/sprint_14_impacts.md` (Sprint 14)
- `/docs/dpia/sprint_15_impacts.md` (Sprint 15)
- `/docs/dpia/sprint_16_impacts.md` (Sprint 16)
- `/docs/dpia/sprint_17_18_impacts.md` (Sprints 17 + 18)

---

## Sprint 19 stories

### US-116 — ChoiceList + ChoiceOption catalogue in REF-DATA

- **New processing activity**: New `ChoiceList` and `ChoiceOption`
  tables in `apps/reference_data/` with versioning, status
  lifecycle, and dual-approval semantics mirroring DqaRule.
  Seed migration loads 46 legacy lists (370 options) from
  `k-forms/build_nsr_xlsform.py` as version 1.
- **Personal-data categories**: None at the catalogue level —
  these are code lists (relationship to head, marital status,
  shock type, etc.). Once a list is referenced by a question and
  intake captures answers, the *answers* are personal data, but
  that lives downstream (Submission / Member rows).
- **Lawful basis**: Public task — code-list catalogue is
  registry plumbing.
- **Data minimisation**: N/A. Catalogue rows don't carry PII.
- **Residual risk**:
  - **Code-list drift**. A poorly authored ChoiceList
    (deprecated option re-purposed) could silently invalidate
    historical answers. Mitigation: deprecate-not-delete is
    enforced at the model layer; the v2 authoring workflow
    requires dual approval (US-116b is its own follow-up
    ticket — services + AuditEvent, mirroring DqaRule).

### US-117a — FormSection / FormQuestion / FormSkipLogic / FormConstraint models

- **New processing activity**: First-class authoring model.
  Adds `status`, `author`, `approved_by`, `approved_at`,
  `submitted_at`, `approval_note`, `rejection_reason` to
  FormVersion; introduces `FormSection`, `FormQuestion`,
  `FormSkipLogic`, `FormConstraint` child tables. The legacy
  `FormVersion.schema` JSONField is now an *output* (regenerated
  from children) rather than the source of truth.
- **Personal-data categories**: None at the schema layer — the
  models describe questions, not answers. `FormQuestion.label`
  is the prompt text; `FormConstraint.message` is validation
  copy. No respondent data.
- **Lawful basis**: Public task — questionnaire authoring is
  registry plumbing.
- **Data minimisation**: N/A for the schema layer.
- **Residual risk**:
  - **Constraint message leakage**. A `constraint_message` or
    `error_message_template` field that includes raw PII would
    leak via `StageRecord.dqa_summary` AND `DqaResult.reason`
    (US-082a). Authors are coached not to include raw NIN /
    phone / DoB in messages; the future rule-editor lint pass
    (open item) should warn on `{nin}` / `{phone}` /
    `{date_of_birth}` interpolation. **DPO action item filed.**

### US-117b — Questionnaire builder admin UI

- **New processing activity**: Custom Django admin change-form
  with a section/question tree + AJAX reorder + an expression
  validator. Gated by `settings.QUESTIONNAIRE_EDITOR_V2`
  (default True dev / False prod). The validator endpoint runs
  user-supplied JSON-DSL through `apps.dqa.engine.evaluate_
  expression` against a user-supplied sample record.
- **Personal-data categories**: The sample record the author
  pastes into the validator IS user-supplied; nothing prevents
  an operator from typing a real-looking record. None of that
  is persisted — the validator returns a result and discards
  the sample. The endpoint emits no AuditEvent today.
- **Lawful basis**: Public task — authoring tool.
- **Data minimisation**:
  - Validator response carries `{ok, result}` or `{ok, error}`
    — never echoes the sample back.
  - Sample is in-memory; no DB write.
- **Residual risk**:
  - **Sample-record exposure in logs**. If an admin DEBUG log
    is on and records request bodies, an author who pastes a
    real intake row into the validator could leak it via log
    files. **DPO action item filed**: confirm production
    request-logging configuration redacts the validator
    endpoint or strips bodies.
  - **No audit on validator calls**. If telemetry shows the
    validator being used as a back-door PII viewer
    (operator pastes 1000 records and infers structure from
    responses), we'd want to add an `AuditReadMixin`-style
    emit. Defer until telemetry suggests it.

### US-118 — XLSForm export from FormVersion

- **New processing activity**: Admin download endpoint
  `/admin/intake/formversion/_us118/export-xlsform/<id>/` that
  streams the authored questionnaire as a Kobo-compatible
  xlsx. Iterates sections/questions/options.
- **Personal-data categories**: None — exports schema only,
  not responses. The xlsx is the same shape Kobo or any other
  XLSForm tool would consume; carries question labels and
  choice catalogues, no PII.
- **Lawful basis**: Public task — exporting the authoring
  output to the field-deployment tool.
- **Data minimisation**:
  - Choices sheet only includes ChoiceLists actually referenced
    by the survey sheet. Lists that exist in the catalogue but
    aren't used by any question are omitted — keeps the file
    smaller and avoids implying "these lists are available at
    intake" when they aren't.
- **Residual risk**: None new. The exported xlsx is the
  authored questionnaire; same trust boundary as the prior
  process where someone hand-ran `k-forms/build_nsr_xlsform.py`.

### US-119 — Rule-pack sync from FormVersion to DAT-DQA

- **New processing activity**: When a FormVersion's
  authoring concludes, `apps.intake.rule_pack_sync.sync_rule_
  pack` creates / updates DqaRule rows mirroring each
  FormQuestion's `FormConstraint.dsl`. The DqaRule's
  `expression` IS the FormConstraint DSL — single source of
  truth.
- **Personal-data categories**: None at the sync level —
  these are rule rows, not answers. Once a synced rule
  evaluates an intake record at DIH, the *failures* end up in
  `DqaResult` (US-082a) where the existing audit pipeline
  applies.
- **Lawful basis**: DPPA accountability + public task —
  evaluation must be reproducible from the authored
  questionnaire.
- **Data minimisation**:
  - One audit event per sync (`rule_pack_synced`), not N per
    question. Reduces noise.
  - DqaRule rows are tagged `author="system-sync"` so the
    DPO can distinguish hand-authored rules from auto-synced
    ones in any future audit query.
- **Residual risk**:
  - **Constraint authoring drift**. If an author edits a
    FormConstraint AFTER a FormVersion is ACTIVE without
    re-syncing, the runtime evaluates against the OLD DqaRule
    while the questionnaire shows the NEW message. Mitigation:
    activating a new FormVersion creates a NEW version-1
    sync — old rules retire, new ones land. **DPO action
    item**: pin the lifecycle so a sync is mandatory on
    transition into ACTIVE; manual sync from admin is a
    convenience for re-syncing, not the primary path.

### US-120 — Legacy questionnaire import script

- **New processing activity**: One-shot script
  `scripts/import_legacy_questionnaire.py` that reads the
  legacy `k-forms/build_nsr_xlsform.py` and builds
  FormVersion v1 = 9 sections / 184 questions.
- **Personal-data categories**: None — the source is the
  schema-defining Python script. No respondent data flows
  through this path.
- **Lawful basis**: Public task — registry plumbing.
- **Data minimisation**: The script reads the schema-only
  legacy file. `docs/06_questionnaire.docx` (the human-readable
  field instrument) is NOT touched by this importer.
- **Residual risk**:
  - **Idempotency on re-run**. The script `update_or_create`s
    on natural keys; re-running can only add or update, never
    delete. A future "delete-and-rebuild" mode would need its
    own ticket + DPO review. Today's behaviour is safe.
  - **Side-effects from exec'ing the legacy file**. The
    legacy script writes an xlsx as a side effect at module
    import; the import_legacy script monkey-patches
    `Workbook.save` to no-op so no file is written. Verified
    in tests + runtime print confirms no save target was
    written outside `/k-forms/`.

### US-S19-005 — DPIA Sprint 19 follow-up

- No new processing activity — this document.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Add a lint pass on FormConstraint.message + FormQuestion.constraint_message that warns on `{nin}` / `{phone}` / `{date_of_birth}` interpolation; mirror in DqaRule.error_message_template authoring | DPO + DQA Author | US-117a |
| Confirm production request-logging configuration redacts the `/admin/intake/formversion/_us117b/validate-expression/` endpoint body (sample-record exposure risk) | Ops + Security | US-117b |
| Decide whether to audit-log validator calls (volume-based abuse signal); defer until telemetry shows usage | DPO | US-117b |
| Pin the FormVersion approval workflow to invoke sync_rule_pack atomically on transition into ACTIVE — manual sync becomes the re-sync convenience, not the primary path | DPO + Engineering | US-119 |
| Confirm system-sync DqaRule rows (author="system-sync") are distinguishable from hand-authored rules in any future DPO audit query | DPO + DBA | US-119 |

Plus the 51 actions still outstanding from prior instalments.

---

## Next review

Sprint 20 close. Sprint 20 candidate set:
- **US-117c**: Drag-and-drop reorder in the Questionnaire builder
  (deferred from US-117b in favour of up/down arrows). DOM-only;
  no model changes.
- **US-119b**: Wire `sync_rule_pack` into the FormVersion.approve
  service action so activation auto-syncs the rule pack atomically.
- **US-S20-001**: Constraint-message PII lint (DPO action item from
  US-117a).
- **Validator audit-log decision**: implement or defer per the
  DPO call.
- **DPIA Sprint 20 follow-up**.
