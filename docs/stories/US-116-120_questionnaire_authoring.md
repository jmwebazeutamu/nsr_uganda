# Questionnaire as a system-driven component

**Epic:** 17. Questionnaire Authoring (new). Sits alongside Epic 1 (Intake) and Epic 16 (DIH).
**Module owners:** apps/reference_data, apps/intake, apps/ingestion_hub.
**Status:** Not started. Replaces today's flow where `k-forms/build_nsr_xlsform.py` hand-codes the XLSForm and Kobo holds the source of truth.

## Why now

Today the questionnaire shape lives in three places: a Python script that generates the XLSForm, a Kobo project that operators edit, and `apps/intake/FormVersion.schema` which snapshots whatever Kobo currently has. Adding one income-source choice means editing the Kobo form by hand, redeploying it, then back-porting the change to DAT-DQA rules, DIH MappingRules, and the canonical schema. The three drift apart on every change.

This block inverts the flow. The system owns the questionnaire. Kobo (and any future CAPI runtime) is a dumb data collection surface that consumes a generated XLSForm. Choice lists, skip-logic, constraints, and field types live in REF-DATA. A version bump on a FormVersion fans out to the rule pack, the mapping rules, and the canonical schema in one transaction.

## Stories

### US-116 — Choice-list catalogue in REF-DATA

**As a** System Admin
**I want** to manage choice lists (income source, education level, disability type, shock type, etc.) as versioned reference data
**So that** I can add or retire options without touching code or Kobo

**Acceptance criteria:**

- New `ChoiceList` and `ChoiceOption` models in `apps/reference_data/` with `list_name`, `code`, `label`, `effective_from`, `effective_to`, `status`, `parent_code` (for cascading lists), `language` (default `en`, supports `lg`, `ny`, `ac`, `xog` in Phase 2).
- ULIDs for external IDs.
- A choice option can be deprecated but never deleted. Deprecated options remain readable for historical records.
- Adding or retiring an option requires dual approval, same workflow as DAT-DQA rules (US-078 pattern).
- Each change writes an AuditEvent.
- Admin UI under `/admin/reference_data/choicelist/` with the same custom-form pattern as the Rule Editor.
- DRF endpoints at `/v1/ref-data/choice-lists/` (list, retrieve, create, update under approval).
- Seed migration loads the existing 14 choice lists currently hard-coded in `k-forms/build_nsr_xlsform.py` as version 1, status active, attributed to `system-migration`.

**Priority:** Must.

---

### US-117 — Questionnaire authoring model

**As a** System Admin
**I want** to author the questionnaire (sections, questions, skip-logic, constraints) inside the system
**So that** the questionnaire shape, the rule pack, and the canonical schema stay in lock-step

**Acceptance criteria:**

- Extend `apps/intake/FormVersion` (or move to `apps/reference_data` if cleaner) with first-class child models: `FormSection`, `FormQuestion`, `FormSkipLogic`, `FormConstraint`.
- `FormQuestion` carries: `name` (snake_case), `label`, `hint`, `type` (text, integer, decimal, date, select_one, select_multiple, geopoint, image, calculate, note, begin_repeat, end_repeat, begin_group, end_group), `choice_list_ref` (FK to `ChoiceList` when type is `select_*`), `required`, `relevant_expression`, `constraint_expression`, `constraint_message`, `appearance`, `repeat_count`, `parameters`, `order_in_section`.
- Expressions use the same JSON-DSL as DAT-DQA where possible; XPath-style expressions are stored as strings for XLSForm export (Kobo expects XPath).
- A FormVersion is immutable once activated. Edits create a new version. Lifecycle: `draft → pending_approval → active → retired`. Same dual-approval pattern as DAT-DQA.
- The activation of a new FormVersion is atomic with the publication step (US-118 below).
- Custom admin UI: section-and-question tree on the left, edit panel on the right. Drag to reorder. Inline validation for relevant/constraint expressions.
- Bulk import of an existing FormVersion from the legacy `k-forms/build_nsr_xlsform.py` output as version 1. One-off migration script under `/scripts/import_legacy_questionnaire.py`.
- Tests: every node type round-trips through save → reload without drift; activation gates pass; admin custom form renders.

**Priority:** Must.
**Depends on:** US-116.

---

### US-118 — XLSForm generator from FormVersion

**As a** System Admin
**I want** the system to emit a Kobo-compatible XLSForm from an active FormVersion
**So that** the data collection tool runs the form the system designed

**Acceptance criteria:**

- New module `apps/intake/xlsform/` containing `exporter.py` that walks a FormVersion and produces a workbook with the three Kobo sheets (`survey`, `choices`, `settings`).
- The exporter respects every column XLSForm expects (`type`, `name`, `label`, `hint`, `required`, `relevant`, `constraint`, `constraint_message`, `appearance`, `choice_filter`, `calculation`, `repeat_count`, `parameters`).
- `select_one` and `select_multiple` types pull options from the referenced `ChoiceList`, filtered to options active on the FormVersion's `effective_from` date.
- Cascading geographic choice lists are emitted with `choice_filter` set to the parent code, matching the current pattern in `k-forms/build_nsr_xlsform.py`.
- `form_id` and `version` in the `settings` sheet match the FormVersion's `id` and `version` exactly.
- Output is byte-for-byte deterministic on the same input (so diffs are meaningful in CI).
- Round-trip test: generate XLSForm → parse it back with `pyxform` → assert the field set and choice options match the source FormVersion.
- Replaces `k-forms/build_nsr_xlsform.py`. Move that file to `/scripts/legacy/build_nsr_xlsform_v0.py` and add a deprecation note in the docstring.
- New management command: `python manage.py export_xlsform --form-version <id> --out path.xlsx`.
- REST endpoint: `GET /v1/intake/form-versions/{id}/xlsform` returns the file with `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

**Priority:** Must.
**Depends on:** US-117.

---

### US-119 — Form-version propagation pipeline

**As the** NSR MIS
**I want** activation of a new FormVersion to fan out to DAT-DQA, DIH MappingRules, and the canonical schema
**So that** the rule pack, the connector mappings, and the data model never lag the questionnaire

**Acceptance criteria:**

- On `FormVersion` activation a signal fires `intake.form_version.activated`. Listeners run in a single transaction inside the activation:
  1. **DAT-DQA**: regenerate the rule pack for the new FormVersion. Rules whose `applicability_filter.form_version` is unbound migrate automatically. Rules pinned to the previous FormVersion are flagged "needs review" and held in `pending_review` until an admin acknowledges.
  2. **DIH MappingRule**: for every active SourceSystem, create a draft MappingRule revision pre-populated by name match between source paths and the new form's question names. Source Admin approves before activation.
  3. **Canonical schema**: a forward-only Django migration is auto-generated under `apps/data_management/migrations/` with the new columns (additive only). Removed questions are not dropped; the column is marked `deprecated_at` and the data is preserved.
- A new admin screen at `/admin/intake/formversion/<id>/propagation/` shows the fan-out status: rule pack rebuilt (Y/N), connector mapping drafts (count, by source), canonical schema migration (file path, applied Y/N).
- Activation fails atomically if any of the three steps fails. The FormVersion remains in `pending_approval` with the error attached.
- Tests: a non-trivial form change (add one income-source option, add one new question, mark one question deprecated) walks the full pipeline and produces the expected artefacts.

**Priority:** Must.
**Depends on:** US-117, US-118, plus existing DAT-DQA (US-076–US-079) and DIH MappingRule (US-106).

---

### US-120 — Kobo XLSForm push connector

**As a** Source Admin
**I want** to push a system-generated XLSForm into a Kobo project
**So that** Kobo runs the form the system designed and there is no manual upload step

**Acceptance criteria:**

- New connector subclass under `apps/ingestion_hub/connectors/kobo_push.py` (sibling to the existing `kobo.py` pull connector).
- Configuration per `SourceSystem`: Kobo URL, project asset ID, API token (read from secrets manager).
- Action: `python manage.py kobo_push --form-version <id> --source <source_code>` calls `POST /api/v2/assets/{asset_uid}/files/` (or asset replace) to upload the generated XLSForm and redeploys the project.
- The push records a `ConnectorRun` with `mode = "push"` and an audit event.
- Once a FormVersion has been pushed to a Kobo project the connector tags the project with the FormVersion id; submissions ingested back via the pull connector are linked to that FormVersion automatically (no operator-side mapping).
- Failure modes: invalid token, project not found, Kobo rejects the asset. Each returns a structured error and writes a Quarantine row with the reason.
- Tests: contract test with a stub Kobo server (use `responses` or `respx`) covering the happy path and the three failures above.

**Priority:** Should.
**Depends on:** US-118, plus existing DIH connector scaffolding.

---

## Sprint slotting

Insert two sessions into `docs/08_sprint_plan.xlsx` Forward sheet ahead of S9 (CAPI). S9 needs the form to be system-owned before it can build the CAPI offline runtime against it.

| Session | Headline | Stories |
|---|---|---|
| S8b (new) | Questionnaire authoring + choice-list catalogue | US-116, US-117 |
| S8c (new) | XLSForm generator + propagation pipeline + Kobo push | US-118, US-119, US-120 |

S9 onwards remain as planned. ADR-0004 (CAPI form runtime) gains a hard dependency on S8b/S8c: whichever runtime is chosen must consume the FormVersion JSON or the generated XLSForm, not its own form schema.

## Dependencies

- US-076–US-079 (DAT-DQA Rule Editor) done. US-119 depends on the rule pack rebuild path being callable.
- US-106 (DIH MappingRule versioning) done. US-119 depends on draft-revision creation.
- ADR-0005 (DQA Rule Editor UI) — pattern reused for the Choice-list and Question editors.

## Anti-patterns to avoid

- Do not let the JSON `FormVersion.schema` field stay as the source of truth alongside the new child tables. Drop it (or mark it `legacy_schema` and stop reading) once US-117 lands.
- Do not allow direct edits to a Kobo form once US-120 lands. The Kobo project becomes a read-only consumer.
- Do not destructively drop columns when a question is deprecated. Audit history requires the data to remain.
