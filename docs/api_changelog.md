# NSR MIS API — Changelog

Notable changes to outbound API contracts. Entries are dated and tied to the commit / story that introduced them. Partner MDAs subscribed to the DRS contract should treat every entry as a candidate for downstream rework.

---

## 2026-05-21 — US-S27-016 — DRS query builder exposes every UBOS geographic level

**Affected endpoints**:
- `/api/v1/drs/requests/builder-schema/` — 6 new `fields` (region, district, county, sub_county, parish, village) + 6 new `filter_fields` entries.
- `/api/v1/drs/requests/{id}/submit/` — `validate_against_dsa` now enforces 7 geographic payload keys (`region_codes`, `sub_region_codes`, `district_codes`, `county_codes`, `sub_county_codes`, `parish_codes`, `village_codes`) instead of just `sub_region_codes`.
- `/api/v1/reference-data/geographic-units/` — `?level=` / `?status=` / `?parent=` query params now actually filter (previously silent no-ops because `filterset_fields` requires django-filter, which isn't installed).

### What changed

- **Backend `FIELD_CATALOGUE`** gains 6 new fields, one per remaining UBOS administrative level. Each is an `enum` with `options_source: geographic-units?level=<level>`. The query builder's value picker fetches the live list at that level.

- **`GeographicUnitViewSet.get_queryset` honours its query params.** This was a long-standing pre-existing bug: `filterset_fields = ["level", "status", "parent"]` requires django-filter, which the project doesn't install. Every URL like `?level=sub_region` was a no-op and returned the whole hierarchy. Fixed by overriding `get_queryset`. Wizard value pickers now actually get level-scoped results.

- **Validator generalised**. `_allowed_sub_region_codes` is now a thin wrapper around `_allowed_geo_codes(dsa, level)`. `validate_against_dsa` walks a `_GEO_PAYLOAD_KEYS` map and rejects extras at any level. A DSA's `geographic_scope` M2M may carry rows at any level (ADR-0011 §4); each level is enforced independently. If the DSA has no rows at a level, that level is unrestricted (existing convention preserved).

- **Wizard option-source URLs fixed**. The previous URL used `status=current` which doesn't exist in the model (model uses `active` / `superseded` / `retired`). Combined with the no-op viewset filter, the bug was invisible; with the filter fix it became live. Wizard now passes `status=active` for every UBOS level. `page_size` calibrated by expected row count (10k for village, 5k parish, 2k sub-county, 500 for coarser levels).

- **Wizard leaf extractors** translate every supported geo leaf in the criteria tree to its flat payload key, so the validator sees them. Adding a new geo level requires no frontend change beyond the catalogue entry.

### What partners can now filter on

Region · Sub-region · District · County · Sub-county · Parish · Village · Programme · Urban/Rural.

Plus everything from US-S27-013 (PMT band, vulnerability band, member.sex / age_years / etc.). The non-geographic, non-programme leaves still land in `request_payload.criteria` as audit-only — the criteria-evaluator is the next slice.

### What hasn't changed

- The wire format for the validator. New geographic payload keys are additive; existing callers continue to work unchanged.
- The DSA scope model. `geographic_scope` is still an M2M to `GeographicUnit`, populated at any level.

---

## 2026-05-21 — US-S27-014 — DRS Step 3 uses the two-pane FieldStepV2 selector

**Affected endpoints**: none. No API contract changes — the wiring is design-layer only. The submit payload's `fields` array is now ORDERED, which the validator already tolerates (it's a set check, not positional).

### What changed

- **Wizard Step 3 is now `<FieldStepV2/>`** from `design/v0.1/screens/screens-drs-fieldselector.jsx` — a two-pane available → ordered-output surface with:
  - **Search** across label / key / description / example
  - **Group + sensitivity** filter pills
  - **DSA-blocked toggle** for explicit visibility
  - **Recommended packs** (Minimum reporting / Geography rollup / Vulnerability profile / Housing & utilities) — one-click presets that load an ordered selection
  - **Drag-reorder** of the selected list (column order in the delivery file follows this sequence)
  - **Sensitivity breakdown** card — counts + bar + DPO-review banner when Personal / Sensitive columns are picked

- **Selected fields are now ordered.** The wizard's `selectedFields` state migrated from `Set<string>` to `string[]`. Submit payload's `fields` array preserves the user's drag order. `validate_against_dsa` is order-insensitive; no server contract change.

- **Template parameterized.** `FieldStepV2` now accepts a `fields` prop. The active catalogue is the live `schema.fields` from `/builder-schema/` (US-S27-013); inline `FS_FIELDS` remains as offline-preview fallback. Field-shape renamed to match the backend's contract (`g` → `group`, `sens` → `sensitivity`, `dsaBlocked` → `disabled`, `dsaReason` → `disabled_reason`). `FSSelected` and `FSBreakdownCard` accept a `byKey` prop so they resolve keys against the live catalogue, not a module-level constant.

- **Inline `FieldStep` removed.** The wizard's prior simple-row Field Selector + the `FIELDS` mock + `effectiveFields` derivation are gone. Step 3 is exclusively `<FieldStepV2/>`.

### What hasn't changed

- No backend changes. `apps/data_requests/builder_schema.py` already advertises `label` + `type` per field (US-S27-013); FieldStepV2 consumes that directly.
- Submit modal labels still cite "X of Y · Z disabled" using the live `builderFields` list.
- PreviewStep (Step 4) still renders hardcoded preview rows — no real match-estimate endpoint yet.

---

## 2026-05-21 — US-S27-013 — DRS uses the nested-tree query builder; full household + member catalogue

**Affected endpoints**: `/api/v1/drs/requests/builder-schema/` field shape gains `label` + `type` + (`options` | `options_source`).

### What changed

- **`builder-schema.fields` are now typed.** Each entry adds:
  - `label` (str) — display label for the wizard
  - `type` — one of `text` / `enum` / `enum-multi` / `number` / `date` / `bool`
  - `options` (inline list of `{value, label}`) for static enums (e.g. `member.sex`, `household.urban_rural`)
  - `options_source` (slug) for dynamic enums whose values come from reference data (`geographic-units?level=sub_region`, `programmes`). The wizard maps slugs → fetch URLs.

  Exactly one of `options` / `options_source` is present on enum-typed fields.

- **The catalogue now covers household + member.** Previous catalogue was 19 mostly-identifier columns; current catalogue covers household identifiers / geography / dwelling / PMT / lifecycle / programmes plus member identifiers / demographics / NIN / contact / flags. Reflects real model columns in `apps/data_management/models.py`.

- **`TestBuilderSchema` is widened.** New contract tests pin:
  - per-field shape (`REQUIRED_FIELD_KEYS` ∪ optional `options`/`options_source`)
  - `type` is one the wizard knows how to render
  - every enum has exactly one of `options` / `options_source`
  - the catalogue covers both `household.*` and `member.*` namespaces

- **Wizard Step 2 is now the nested-tree query builder** from `design/v0.1/screens/screens-drs-querybuilder.jsx`. AND/OR groups, recursive nesting, full operator surface per type (eq / neq / in / not_in / between / contains / starts_with / set / unset / lastN / is_true / is_false). The template was parameterized so its `fields` prop accepts the live catalogue; an offline-preview `QB_FIELDS` constant remains as a fallback.

- **Submit payload now carries the full criteria tree.** `request_payload.criteria = {kind, combinator, rules:[...]}`. For back-compat with the existing validator (`validate_against_dsa` reads flat `sub_region_codes` + `programme_codes`), the wizard also walks the tree on submit and extracts those two predicate types as flat keys — same shape the validator already understands.

### What this means for partners

- You can now build queries like *"head_sex = 'F' AND (age_years BETWEEN 18 AND 49) AND household.sub_region_code IN ('SR-KARAMOJA', 'SR-ACHOLI')"* in the UI.
- **Today's enforcement is partial.** Only the `household.sub_region_code` and `household.programme_codes` predicates currently filter the result set server-side. Other rules are recorded in the audit chain (via `request_payload.criteria`) but don't yet narrow the query output. The submit modal flags this explicitly.
- A future slice adds the criteria evaluator on `apps/data_requests/services.py` so all predicates filter for real. The wire format won't change.

### What hasn't changed

- The flat-key payload contract. `request_payload.fields`, `sub_region_codes`, `programme_codes`, `max_rows`, `requester_note` still work as before.
- The `filter_fields` catalogue from US-S27-012 stays in the schema response for the simple-row builder fallback if any tooling still consumes it. Wizard ignores it now.
- Operator-side approve/reject + partner download remain unchanged.

---

## 2026-05-21 — US-S27-012 — DRS query builder is now schema-driven

**Affected endpoints**: `/api/v1/drs/requests/builder-schema/` adds one top-level key.

### What changed

- **`GET /api/v1/drs/requests/builder-schema/` now returns `filter_fields`** — a catalogue of the predicates `validate_against_dsa` actually evaluates. Each entry:

  ```json
  {
    "key": "household.sub_region_code",
    "label": "Sub-region",
    "operators": ["in"],
    "value_source": "/api/v1/reference-data/geographic-units/?level=sub_region&status=current&page_size=200",
    "value_type": "multi_code",
    "payload_key": "sub_region_codes",
    "value_code_field": "code",
    "value_label_field": "name"
  }
  ```

  Today the catalogue is `household.sub_region_code` and `programme`. The UI grows automatically when the backend gains a new predicate — append an entry to `FILTER_FIELDS` in `apps/data_requests/builder_schema.py`.

- **`TestBuilderSchema` is widened** to pin the catalogue's shape (`EXPECTED_FILTER_FIELD_KEYS`) and to assert every `payload_key` is one the validator actually reads. The latter is the contract: schema can advertise only what the backend can act on.

- **The wizard's Step 2 is now a real query builder.** Each predicate is a row: field dropdown (from `filter_fields`), operator label (from `field.operators`), value multi-select (lazy-fetched from `value_source`). Rows AND together. "Add filter" appends a row; per-row × removes it. Row-cap (`max_rows`) stays as a separate input below the predicate rows because it's a LIMIT, not a WHERE.

- **Submit translation**: each row maps to its field's `payload_key`. Multiple rows on the same field union their values. The result is the same flat `request_payload` shape `validate_against_dsa` already accepts — no backend protocol change.

- **Submit modal + summary card** walk `filterRows` to show real predicates rather than counts of two specific dimensions.

### What hasn't changed

- **The validator contract**. `validate_against_dsa` still reads `fields / sub_region_codes / programme_codes / max_rows`. The schema-driven UI emits the same shape.
- **Operators**. Today every `filter_field` advertises `["in"]`. The wizard renders the operator as a fixed label; when a future predicate offers more than one operator, the row gains a real operator dropdown — no UI restructuring needed.
- **Custom AST / nested groups / OR**. Out of MVP scope. The current "all rows AND together" semantic is what the validator supports; richer expression evaluation would need a query planner on `apps/data_requests`.

---

## 2026-05-20 — US-S27-011 — DRS query builder wired end-to-end

**Affected endpoints**: no API contract changes. The wiring is purely on the design harness — the wizard now collects real query-builder state and POSTs it into the existing `request_payload` shape.

### What changed

- **`ScopeStep` is a real controlled radio.** Entity choice (`household` | `member`) is captured in wizard state. Referral / grievance entities remain disabled per MVP DRS scope. The selected entity travels into the request via the `requester_note` field (see below).
- **`BuildStep` is now a real filter builder**, scoped to what `validate_against_dsa` actually accepts:
  - **Sub-region multi-select** populated from `GET /api/v1/reference-data/geographic-units/?level=sub_region`. Selected codes flow into `request_payload.sub_region_codes`.
  - **Programme multi-select** populated from `GET /api/v1/programmes/?status=active`. Selected codes flow into `request_payload.programme_codes`.
  - **Row cap** numeric input. Flows into `request_payload.max_rows`. Blank → omitted; the DSA's `monthly_row_budget` still gates delivery server-side.
  - The prior "AND group / nested group / type-aware operator" stub was removed. That UI would need a query AST evaluator the backend doesn't have; intentionally left for a follow-up beyond MVP.
- **`DeliveryStep` lists the live `schema.delivery_methods`**. Selected method does NOT flow into `request_payload` (the validator doesn't have a delivery slot — DRS-O-02 will add one); it travels via `requester_note` so the operator can honour it at delivery time.
- **`SubmitStep` summary card** mirrors the captured state (DSA reference, entity, sub-regions, programmes, row cap, field count, delivery). No more "~47,233 rows" fiction.
- **`confirmSubmit` posts a real payload**: `request_payload = {fields, sub_region_codes?, programme_codes?, max_rows?}`, top-level `dsa` and `requester_note = "entity=… · delivery=…"` so the audit chain captures the partner's intent.

### Backend behaviour observed by this slice

- The existing `DataRequestSerializer` already exposes `requester_note` as a writable field at create time. No backend code change in this slice.
- `validate_against_dsa` enforces sub-region codes against the DSA's `geographic_scope` and programme codes against the DSA's `programmes` relation; field groups against `field_scope`; `max_rows` against `monthly_row_budget` plus the trailing-30d cumulative budget. Any violation surfaces verbatim in the wizard's toast.

### What still isn't wired

- **Purpose / retention / recipient list inputs on the SubmitStep**. The DataRequest model carries `requester_note` (one free-text field) but not separate columns for these. Adding them is a model change that belongs in the DPO review surface slice, not the wizard.
- **PreviewStep** still renders hardcoded household rows. A real match-estimate / sample endpoint would need to live in `apps/data_requests` first.

---

## 2026-05-20 — US-S27-010 — DRS pipeline wiring (builder-schema `dsa_id`, submit, download)

**Affected endpoints**: `/api/v1/drs/requests/builder-schema/` adds one field; the request submit + bundle download flows are now wired end-to-end from the DRS wizard and partner portal.

### What changed

- **`GET /api/v1/drs/requests/builder-schema/` now returns `dsa_id`**
  alongside `dsa_reference`. The id is the ULID of the user's active
  DSA (partner roles) or the empty string (operator roles). The
  wizard needs the id to `POST /api/v1/drs/requests/` and the
  reference for human-readable display. The
  `TestBuilderSchema.EXPECTED_TOP_LEVEL_KEYS` contract test was
  widened to include the new key — frontends that destructure the
  response should add it. The role-parity tests still pass (the
  shape is identical across roles; values differ).

- **DRS wizard now submits real DataRequests.** Previously the
  wizard's "Submit for approval" button only fired a toast. It now:
  1. Reads `dsa_id` from the builder-schema response.
  2. POSTs `{dsa, request_payload}` to `/api/v1/drs/requests/` —
     `request_payload.fields` carries the dotted keys
     (`household.id`, `member.first_name`) the validator
     understands; the wizard collects them directly from the live
     schema.
  3. POSTs `/api/v1/drs/requests/{id}/submit/` which runs
     `validate_against_dsa`. A scope violation surfaces the server's
     exact reason in the wizard's toast (e.g. "`fields=['member.nin_hash']
     outside DSA scope (allowed field_scope=['Identifiers'])`").
  4. On success, exits the wizard to the host's list view.
  Behaviour when there is no active DSA (operator role, partner
  with no `OperatorScope`): the submit modal opens but the Submit
  button surfaces "No active DSA for your account — submission
  unavailable" rather than fabricating a successful toast.

- **Partner DRS portal "Download" button now downloads.** Previously
  it just toasted the row count. It now fetches the credentialed
  `GET /api/v1/drs/requests/{id}/download/` endpoint, converts the
  NDJSON bytes to a blob, and triggers a browser download as
  `drs-{id}.ndjson`. When DRS-O-02 closes (MinIO + signed URLs) the
  endpoint will return a 302 to the signed URL; the partner-side
  UX is unchanged because anchor-driven downloads follow redirects.

### What hasn't changed yet (honest deferral)

- **Filter editor**: the wizard's BuildStep still renders hardcoded
  filter rows (Karamoja + West Nile, PMT band, etc.). They're
  presentation-only — submit doesn't include any `sub_region_codes`
  or `programme_codes` because the wizard doesn't collect them. The
  submit modal flags this as "filter editor wiring pending".
- **Row cap**: `request_payload.max_rows` is omitted on submit. The
  DSA's `monthly_row_budget` still gates delivery server-side.
- **Delivery method**: the DeliveryStep is presentation-only;
  `delivery_methods` from the builder-schema isn't consumed yet.
- **Operator-side wizard**: operators don't have an active partner
  DSA, so the wizard surfaces "Operators submit on behalf of
  partners; no DSA bound to this session". The operator-side
  approve/reject actions on the inbox list (US-S14-002) continue
  to work as before.

These three are the remaining wizard slice for a future ticket;
they need real form state on entity choice, filter expression,
max_rows, and delivery method.

### No audit-event vocabulary changes

The submit chain emits the existing `submit` action via
`apps.data_requests.services.submit_data_request`; the download
emits the existing `download` action via the bundle endpoint.

---

## 2026-05-20 — US-S27-005 / ADR-0016 — DSA renewal endpoint + supersession on activation

**Affected endpoints**:

| New                                  | Behavioural change                                    |
|--------------------------------------|-------------------------------------------------------|
| `POST /api/v1/dsas/{id}/renew/`      | Sign-off activation now supersedes prior active v(N) |

### What changed

- **`POST /api/v1/dsas/{id}/renew/`** is the new renewal action.
  - **Active source**: clones v(N) into a fresh v(N+1) draft. Scope
    is copied verbatim — no edits. `programmes` + `geographic_scope`
    M2M are copied. `effective_from` and `effective_to` are reset
    to NULL so the operator can fill in the next effective window.
    `signed_at` is NULL. Signatures are empty. Returns the new draft.
    Emits two audit events on the new row: `clone` (from the shared
    primitive) and `dsa_renewed` with `field_changes={source_dsa_id,
    source_version, new_version}`.
  - **Renewed source** (OI-S27-2): silently redirects to the latest
    active version of the same `reference` (no new clone, no audit).
    If no active successor exists, returns 400.
  - **Any other status** (`draft`, `pending_signature`, `expiring`,
    `expired`, `suspended`) → 400 with the message
    "`DSA {reference} v{version} cannot be renewed in status {status!r}`".

- **Sign-off activation now supersedes the prior active version.**
  When `record_signature` flips a DSA to `status="active"` (i.e. all
  three signatures are signed per ADR-0012), the activation step
  now also:
  1. Finds every DSA whose `reference` matches and whose `status` is
     currently `active`, excluding the row that just activated.
  2. For each prior, re-points every `Programme.dsa` FK pointing at
     that prior to the newly active row.
  3. Flips the prior's `status` to `renewed` (terminal).
  4. Emits a `dsa_superseded` audit event on the prior with
     `field_changes={superseded_by, new_version,
     programme_ids_repointed}`.

  The entire transition runs inside the existing `@transaction.atomic`
  on `record_signature`. Per ADR-0011 there is at most one active
  version per reference at any moment; the implementation handles N
  defensively (e.g. a manual DB edit that left two priors active).

- **DRS enforcement is unchanged.** `apps.data_requests.services.validate_against_dsa`
  already filters by `status="active"`, so v(N) drops out of
  validation the instant supersession flips its status. The
  `monthly_row_budget` double-counting risk during a renewal overlap
  window is structurally impossible — there's exactly one row with
  `status="active"` per reference once the new v+1 lands.

### New audit-event actions

| Action            | Fired on                                              | `field_changes` keys                                          |
|-------------------|-------------------------------------------------------|---------------------------------------------------------------|
| `dsa_renewed`     | Successful `POST /renew/` on an active DSA            | `source_dsa_id`, `source_version`, `new_version`              |
| `dsa_superseded`  | A prior-version DSA transitioning to `renewed` because its successor activated | `superseded_by`, `new_version`, `programme_ids_repointed` |

(`clone` was added in US-S27-003 and continues to fire from the
shared `clone_to_draft` primitive on both `/edit-scope/` and
`/renew/`.)

### What hasn't changed

- **No new `dsa_status` ChoiceList codes** — `renewed` was already
  seeded in `choice_lists_partners_v1.json` from Sprint 23.
- **`/api/v1/dsas/{id}/submit-for-signoff/`** still drives the
  sign-off chain unchanged. The activation step inside
  `record_signature` is the only thing that gained behaviour.
- **The informational `renewing` indicator** from ADR-0016 (a
  derived state showing "v+1 draft pending" on the parent active
  row) is not implemented in this slice — it lands with US-S27-004
  (cross-partner workbench) where the dashboard surface needs it.

---

## 2026-05-20 — US-S27-003 / ADR-0016 — DSA scope-edit endpoint + version-bump on active

**Affected endpoints**:

| New                                            | Effect on existing                                 |
|------------------------------------------------|----------------------------------------------------|
| `POST /api/v1/dsas/{id}/edit-scope/`           | `PATCH /api/v1/dsas/{id}/` now rejects active rows |

### What changed

- **`POST /api/v1/dsas/{id}/edit-scope/`** is the new orchestrating
  action for scope changes. Body: any subset of `field_scope`,
  `entities_scope`, `monthly_row_budget`, `sensitive_data_handling`,
  `retention_days`, `classification`, `dpia_document_ref`,
  `breach_sla_hours`, `geographic_scope_ids`. Unknown keys are
  ignored. Returns the DSA row the operator should display.

  - **Draft DSAs**: changes land in place. Same `id`, same `version`,
    no signature requirement. One `dsa_scope_changed` audit event
    is emitted with `field_changes={before, after, version, editor}`.
  - **Active DSAs**: per ADR-0016 §"Decision 2", an active DSA is a
    signed legal instrument and its scope cannot mutate. The action
    clones v(N) into a fresh v(N+1) **draft** (same `reference`,
    `version+1`, programmes + geographic_scope M2M copied verbatim,
    `effective_from`/`effective_to`/`signed_at` reset to NULL,
    signatures empty). The requested changes apply to the clone;
    v(N) is left untouched at `status="active"`. The returned row
    is the new draft, ready for the existing
    `/submit-for-signoff/` flow. Two audit events are emitted:
    `clone` on the new row (with `source_dsa_id`, `source_version`,
    `new_version`) and `dsa_scope_changed` on the new row.
  - **Any other status** (`pending_signature`, `expiring`, `expired`,
    `suspended`, `renewed`) → 400 with the message
    "`DSA {reference} v{version} cannot be scope-edited in status {status!r}`".

- **`PATCH /api/v1/dsas/{id}/` now rejects active rows** with HTTP
  400 and a body `{detail, edit_scope_url}` pointing to the
  `/edit-scope/` action. Drafts continue to PATCH in place as
  before. This is the supporting guard for ADR-0016 §"Decision 2".

- **`DataSharingAgreement.reference` is no longer `unique=True`**.
  Uniqueness is now enforced solely by the existing composite
  `UniqueConstraint(reference, version)`. Required so a v(N+1)
  clone can share the partner-stable reference of v(N) (per
  ADR-0011 + ADR-0016 §"Decision 3"). Migration
  `partners/0007_dsa_reference_unique_drop.py` (forward-only).

### New audit-event actions

| Action               | Fired on                                    | `field_changes` keys                                  |
|----------------------|---------------------------------------------|-------------------------------------------------------|
| `dsa_scope_changed`  | Successful `/edit-scope/` on any allowed status | `before`, `after`, `version`, `editor`            |
| `clone`              | Successful clone of v(N) → v(N+1) draft     | `source_dsa_id`, `source_version`, `new_version`      |

`AuditEvent.action` is a 64-char `CharField` whose `choices=` list
is an authoring-time hint only (the column accepts any string up
to its `max_length` — see the comment in `apps/security/models.py`).
Both new actions slot in without a schema change.

### What hasn't changed yet

- **`Programme.dsa` FK is NOT re-pointed on `/edit-scope/`**. Per
  ADR-0016 §"Decision 4" the re-point happens only when the new
  v(N+1) reaches `status="active"`. That step lands with US-S27-005
  (renewal supersession) alongside the `dsa_superseded` audit
  action.
- **No new endpoint accepts the `programmes` M2M as a scope
  change.** Programme attachments / detachments are a separate
  workflow and stay on the canonical `/api/v1/programmes/` write
  surface.
- **`POST /api/v1/dsas/{id}/renew/`** is documented in ADR-0016
  but lands with US-S27-005. The internal `clone_to_draft` helper
  this story added in `apps.partners.services.scope` is the shared
  primitive both endpoints call.

---

## 2026-05-20 — US-S26 / ADR-0015 — referral.Programme consolidation + /api/v1/beneficiaries/

**Affected endpoints**:

| Removed                          | Replacement                                  |
|----------------------------------|----------------------------------------------|
| `GET /api/v1/ref/programmes/`    | `GET /api/v1/programmes/` (US-S23-008, S25)  |

Plus the new `/api/v1/beneficiaries/` listing, two new ChoiceLists,
and `<field>_label` companions on `/api/v1/ref/referrals/` and
`/api/v1/ref/enrolments/`.

### What changed

- **Two `Programme` classes were collapsed into one.** Per ADR-0015,
  the legacy `apps.referral.Programme` model is gone; the canonical
  `apps.partners.Programme` (Sprint 23 + 25) is now the only
  Programme row in the registry. `Referral.programme` and
  `ProgrammeEnrolment.programme` FKs were repointed; existing rows
  (zero in dev / staging) get their FK values rewritten by a
  remap+repoint migration.
- **`apps.referral.ReferralStatus` and `EnrolmentStatus` TextChoices
  were dropped** (the last live TextChoices in the active codepath).
  Both fields are now plain `CharField(max_length=32)` resolving
  against ChoiceLists per ADR-0010. The data migration also
  renames `ProgrammeEnrolment.status='enrolled'` rows to `'active'`
  to match the seeded `programme_enrolment_status` ChoiceList
  vocabulary (ADR-0015 §"Decision 4").
- **Webhook signing now reads the cleartext from
  `Programme.webhook_secret_encrypted`** (an `EncryptedBinaryField`
  using the same KMS path as `PartnerContact.nin_value`). This is
  a documented exception to ADR-0014's hash-only stance because
  HMAC signing needs the cleartext at send time. The
  `WebhookCredential` factoring (OI-S26-3) is the long-term
  successor; the encrypted column is interim.

### New endpoint

| Method | Path                       | Purpose |
|--------|----------------------------|---------|
| GET    | `/api/v1/beneficiaries/`   | Per-programme enrolment ledger. One row per (household, programme). Status synthesised: explicit ProgrammeEnrolment status, or `pending` for sent/accepted Referrals without an enrolment yet. ABAC: combined partner + geographic. |

Filter parameters: `programme`, `programme_code`, `status`,
`sub_region`, `exit_code`, `kind`, `q` (search across head name +
household id + parish + district). Page-number pagination,
default page_size=50, max=200. A cursor-paginated aggregate
endpoint replaces this approach at production scale (OI-S26-5).

### Response shape (excerpt)

Every row carries both raw `<field>` and resolved `<field>_label`:

```json
{
  "id": "01...",
  "household_id": "01...",
  "household_head_name": "Nsubuga Ruth",
  "household_sex": "2",
  "district": "Lyantonde",
  "parish": "Kibalinga",
  "sub_region_name": "Buganda South",
  "programme_code": "OPM-PDM",
  "programme_kind": "cash_transfer",
  "programme_kind_label": "Cash transfer",
  "unit_of_enrolment": "household",
  "unit_of_enrolment_label": "Household",
  "status": "active",
  "status_label": "Active",
  "enrolled_at": "2026-04-10",
  "months_in": 1,
  "exit_code": null,
  "exit_code_label": null,
  "pmt_score": 0.42,
  ...
}
```

### New ChoiceList seeded at v1 / active

```
referral_status   (sent, accepted, enrolled, rejected, exited)
```

External consumers who resolve labels via the bundle endpoint
pick this up automatically. The ETag changes.

### `<field>_label` companions on REF endpoints

`GET /api/v1/ref/referrals/` and `GET /api/v1/ref/enrolments/`
now return `status_label` alongside the raw `status`. Same
shape as Sprint 23's partner-module endpoints.

---

## 2026-05-19 — US-S25-006/007 — Beneficiary registry screen wired; programme_enrolment_status ChoiceList

**Affected endpoints**: extends `/api/v1/reference-data/choice-list-bundle/` with one new list.

### New ChoiceList seeded at v1 / active

```
programme_enrolment_status   (active, suspended, pending, exited)
```

The beneficiary registry screen at
`design/v0.1/screens/screens-beneficiaries.jsx` reads status tabs,
chips, and the tweaks-panel radio from this list. Adding a new
status (e.g. `terminated`) becomes a single ChoiceList row plus
three lines in the UI tone/icon/sub maps; no JSX code change to
the screen itself.

### No new endpoints

The screen reads `/api/v1/programmes/?status=active` (Sprint 25)
to populate the programme rollup strip, and
`/api/v1/reference-data/geographic-units/` to populate the
sub-region filter. The enrolment listing itself is design-preview
data pending the consolidated enrolment endpoint (OI-S25-4 —
slated for Sprint 26 alongside the `apps.referral.Programme` →
`apps.partners.Programme` consolidation).

---

## 2026-05-19 — US-S25 / ADR-0014 — Programme registration wizard wired (POST /api/v1/programmes/)

**Affected endpoints**: new `/api/v1/programmes/` namespace and the
convenience `/api/v1/partners/{id}/programmes/` lister. Extends
`/api/v1/reference-data/choice-list-bundle/` with 8 new lists.

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/programmes/`                       | List programmes. Filters: `partner`, `status`, `kind`, `q`. ABAC-scoped per `PartnerScopedQuerysetMixin`. |
| POST   | `/api/v1/programmes/`                       | Create a draft Programme. Gated by `PARTNERS_MODULE_ENABLED`. |
| GET    | `/api/v1/programmes/{id}/`                  | Retrieve. |
| PATCH  | `/api/v1/programmes/{id}/`                  | Update. |
| GET    | `/api/v1/partners/{id}/programmes/`         | Convenience lister for the partner detail screen. |

### POST shape

The wizard submits a single JSON payload. Required: `partner`,
`name`, `kind`. Optional fields drive the cohort, disbursement,
geographic, lifecycle, and webhook strips:

```json
{
  "partner":             "01J...",
  "code":                "MGLSD-DVA",
  "name":                "Direct Income Support · vulnerable adolescents",
  "summary":             "Monthly cash to female-headed HHs",
  "kind":                "cash_transfer",
  "dsa":                 "01J...",
  "unit_of_enrolment":   "household",
  "cohort_target":       18000,
  "sex_filter":          "2",
  "age_min":             14,
  "age_max":             18,
  "pmt_bands":           ["poorest_20", "poorest_40"],
  "composition_flags":   ["female_headed"],
  "amount_ugx":          75000,
  "disbursement_cycle":  "monthly",
  "duration_months":     24,
  "channel":             "MTN MoMo · agent",
  "start_month":         "Aug 2026",
  "geographic_units":    ["01J...","01J..."],
  "exit_codes_allowed":  ["10","20","30","40","50","60","70"],
  "auto_exit_triggers":  ["age_out","deceased","pmt_shift"],
  "suspend_on_grievance": true,
  "webhook_url":         "https://partner.example.go.ug/webhook"
}
```

The create response echoes every coded field with its resolved
`<field>_label` (Cash transfer, Household, Female, Monthly, …) per
the ADR-0010 contract. The response also carries
`webhook_secret_cleartext` — a one-shot field returned at create
time only; only `sha256(secret)` is persisted on the row.

### New ChoiceLists seeded at v1 / active

```
programme_unit_of_enrolment   (household, member, group)
programme_disbursement_cycle  (monthly, quarterly, semi_annual, annual, one_off)
programme_pmt_band            (poorest_20, poorest_40, middle_40, top_20)
programme_exit_reason         (10..99 — graduated, transferred, deceased, ...)
programme_composition_flag    (female_headed, under_five, elderly, pregnant, disabled, orphan)
programme_auto_exit_trigger   (age_out, deceased, pmt_shift, missed_3)
programme_webhook_event       (referral.sent, referral.accepted, enrolment.created, ...)
programme_sex_filter          (any, 1=Male, 2=Female)
```

Two new options appended to existing `programme_kind`: `grant`, `subsidy`.
Consumers caching the bundle offline pick them up via the ETag.

### New audit-event action

- `programme_created` — fired on every successful create. The
  `field_changes` payload is structured:
  `{partner_id, partner_code, code, kind, cohort_target}`. Same
  shape as the Sprint 23 dashboard activity feed.

### Feature flag

`PARTNERS_MODULE_ENABLED` gates writes (POST / PATCH). Reads are
open under the standard `IsAuthenticated` permission.

### Unique-code semantics

`Programme.code` is unique per partner *only when non-empty*. The
serializer skips DRF's auto-generated `UniqueTogetherValidator`
(which would mark `code` as required) and does a manual partial-
uniqueness check in `validate()`. Empty-string `code` is permitted
so partner Data Stewards can park a draft before naming it.

---

## 2026-05-19 — US-S24 / ADR-0013 — DRS-side Partner + DSA endpoints removed; consolidated under /api/v1/partners/ and /api/v1/dsas/

**Affected endpoints**:

| Removed | Replacement |
|---|---|
| `GET /api/v1/drs/partners/` | `GET /api/v1/partners/` (US-S23-008) |
| `GET /api/v1/drs/partners/{id}/` | `GET /api/v1/partners/{id}/` |
| `GET /api/v1/drs/agreements/` | `GET /api/v1/dsas/` (US-S23-010) |
| `GET /api/v1/drs/agreements/{id}/` | `GET /api/v1/dsas/{id}/` |

### What changed

- Two parallel `DataSharingAgreement` (and two `Partner`) classes coexisted on `main` after Sprint 23 — one in `apps/data_requests/` (pre-existing US-S19), one in `apps/partners/` (Sprint 23). ADR-0013 consolidates onto `apps/partners/`. The DRS-side classes are deleted; their endpoints with them.
- `DataRequest.dsa` FK now targets `apps.partners.DataSharingAgreement`. Response shapes for `GET /api/v1/drs/requests/...` are unchanged (the FK reference is opaque to the consumer).
- The canonical endpoints already carry the same ABAC scoping (`PartnerScopedQuerysetMixin`) the DRS-side endpoints did. Partner-affiliated users see only their own partner; NSR Unit / national / superuser see all.

### DSA scope shape change

The canonical DSA shape differs from the legacy DRS-side one. External consumers that GET a DSA see a different JSON:

| Legacy field | Canonical field |
|---|---|
| `allowed_scopes.fields` | `field_scope` dict (`{"household": true, "member": true}`) |
| `allowed_scopes.sub_region_codes` | `geographic_scope` M2M to GeographicUnit (response includes resolved sub_region codes) |
| `allowed_scopes.programme_codes` | `entities_scope.programmes_allowed` until the structured Programme M2M lands |
| `allowed_scopes.max_rows_per_request` | `monthly_row_budget` |
| `valid_from` / `valid_to` | `effective_from` / `effective_to` |

### Field-scope granularity (read carefully)

The canonical `field_scope` gates at **group level** (`household`, `member`, `pmt`, ...) rather than per-field. A DSA granting the `member` group exposes every `member.*` field in `apps/data_requests/builder_schema.FIELD_CATALOGUE` — including the masked `nin_hash` / `nin_last4`. The legacy `allowed_scopes.fields` supported per-field gating.

Partners with sensitive per-field requirements: please raise; a tighter gating story is `OI-S24-3` in ADR-0013.

### New audit-event actions

Two new AuditEvent action codes land:

- `dsa_scope_violation` — fired by the validator when a request asks for a field group, sub-region, or programme outside the DSA.
- `dsa_budget_exceeded` — fired when trailing-30d rows + this request's `max_rows` would push the partner over their `monthly_row_budget`.
- `data_request_delivered` — renamed from `deliver`. The `field_changes` payload is now structured: `{partner_code, partner_id, dsa_reference, rows_delivered, manifest_sha256, expires_at}`. Consumers reading the audit chain should expect both names during the transition window and switch to `data_request_delivered` going forward.

### New gates (Partners module)

- **Partner-status gate**: `POST /api/v1/drs/requests/{id}/submit/` returns 400 with `detail: "Partner X is suspended"` when the partner's status is `suspended`. The DPO operationally pauses a partner by setting the status via `/admin/partners/partner/`.
- **Budget gate**: returns 400 with `detail: "trailing-30d usage N + this request M would exceed DSA budget B"` when the submit would breach the partner's monthly row budget.

---

## 2026-05-19 — US-S23 — Partners + DSA registry API

**Affected endpoints**: new namespace under `/api/v1/partners/` and `/api/v1/dsas/`. Also extends `/api/v1/reference-data/choice-list-bundle/`.

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/partners/`                 | List partners; filters `q`, `type`, `status`, `sector`. |
| POST   | `/api/v1/partners/`                 | Create a partner. Gated by `PARTNERS_MODULE_ENABLED`. |
| GET    | `/api/v1/partners/{id}/`            | Retrieve. |
| PATCH  | `/api/v1/partners/{id}/`            | Update. |
| GET    | `/api/v1/partners/summary/`         | KPI counts for the dashboard. |
| GET    | `/api/v1/partners/renewals/?days=`  | DSAs by days-until-expiry. |
| GET    | `/api/v1/partners/sector-mix/`      | Partner counts + rows-delivered per sector. |
| GET    | `/api/v1/partners/top-consumers/?n=`| Top N requesters by 30d row volume. |
| GET    | `/api/v1/partners/{id}/activity/`   | Activity feed projection over `AuditEvent`. |
| GET    | `/api/v1/partners/{id}/usage/?days=`| Per-day usage rollup. |
| GET    | `/api/v1/dsas/`                     | List DSAs; filters `partner`, `status`. |
| POST   | `/api/v1/dsas/`                     | Create a draft DSA. |
| GET    | `/api/v1/dsas/{id}/`                | Retrieve with embedded signatures. |
| PATCH  | `/api/v1/dsas/{id}/`                | Update. |
| POST   | `/api/v1/dsas/{id}/submit-for-signoff/` | Workflow trigger (ADR-0012). |

### Bundle endpoint extension

`GET /api/v1/reference-data/choice-list-bundle/?lists=a,b,c` — new `lists` query param trims the bundle to the named ChoiceLists. The wizard fetches just the option sets it needs (`partner_type`, `partner_sector`, `partner_contact_role`, `programme_kind`, `dsa_signer_role`, `signature_method`, `sensitive_data_handling`, `dsa_wizard_step`) instead of the full 60-list catalogue. ETag differs per `lists` allowlist, so each slice caches independently.

### ChoiceList catalogue additions

14 new ChoiceLists seeded at v1/ACTIVE — these are the option sets every partner-module dropdown reads from:

```
partner_type, partner_sector, partner_status, ui_tone,
partner_contact_role, programme_kind, programme_status,
dsa_status, sensitive_data_handling, dsa_signer_role,
signature_method, signature_status, partner_activity_kind,
dsa_wizard_step
```

External consumers that resolve labels via the bundle endpoint pick them up automatically. Consumers caching the catalogue offline must re-fetch (ETag changes).

### Coded-field response shape

Every coded field on every partner-module response carries both raw `<field>` and resolved `<field>_label` — same contract as the household-detail payload from US-S22-005. For example:

```json
{
  "id": "01...",
  "code": "OPM",
  "type": "ministry",
  "type_label": "Ministry",
  "sector": "social_protection",
  "sector_label": "Social Protection",
  "status": "active",
  "status_label": "Active",
  ...
}
```

### Workflow contract

`POST /api/v1/dsas/{id}/submit-for-signoff/` accepts `partner_signer_email`, `nsr_unit_lead_email`, `dpo_email` (and optional name fields). The three emails must be distinct (self-sign-off prohibition). Creates three `DsaSignature` rows; dispatches the first DocuSign envelope (or the stub, depending on `PARTNERS_DOCUSIGN_ENABLED`); emits `AuditEvent`s per ADR-0012.

### Feature flag

`PARTNERS_MODULE_ENABLED` (default `True` in dev; toggleable in production deployment settings) gates write endpoints (POST/PATCH). Reads remain open under the standard `IsAuthenticated` permission.

---

## 2026-05-19 — US-S22-005 — Coded fields now serialise as raw `ChoiceOption.code` strings

**Affected endpoints**: `GET /api/v1/data-management/households/{id}/` and `/members/{id}/`. Any DRS export bundle that includes these fields (per the active Data Sharing Agreement).

### What changed

Three column families now persist and return their raw `ChoiceOption.code` from the seeded `ChoiceList` catalogue instead of the legacy `TextChoices` strings:

| Field | Old value | New value | Seed list |
|---|---|---|---|
| `Member.sex` | `"M"`, `"F"` | `"1"`, `"2"` | `sex` (1=Male, 2=Female) |
| `Member.nin_status` | `"has_card"`, `"lost"`, `"not_issued"`, `"no"`, `"unknown"` | `"1"`, `"2"`, `"3"`, `"4"`, `"8"` | `nin_status` (1=Yes has card, 2=Yes lost, 3=Not issued, 4=No, 8=Don't know) |
| `Household.urban_rural` | `"urban"`, `"rural"` (and unused `"peri_urban"`) | `"1"`, `"2"` | `rural_urban` (1=Urban, 2=Rural) |

This applies to current rows (data migration 0005 rewrote in-place) and all future writes.

### What partner consumers need to do

Two paths, pick one:

1. **Resolve labels server-side via the bundle endpoint** (recommended for any consumer that renders the values to humans):
   ```
   GET /api/v1/reference-data/choice-list-bundle/?as_of=YYYY-MM-DD&lang=en
   ```
   Returns the full catalogue. ETag-cacheable. The response shape is `{as_of, lang, lists: [{list_name, version, options: [{code, label, sort_order, parent_code}]}]}`. Cache locally; re-fetch on ETag change.

2. **Read the `<field>_label` companion field** on the household / member payload itself:
   ```
   GET /api/v1/data-management/households/{id}/
   →  { ..., "urban_rural": "1", "urban_rural_label": "Urban", ... }
   ```
   Every coded column ships both the raw code and the resolved label. The label is computed against the `ChoiceList` version active at the household's intake date (StageRecord created_at), so historical records keep their historical labels.

### Audit-blob shape — unchanged

`source_payload` on the household detail endpoint remains bit-for-bit identical to what DIH ingested. Labels for the questionnaire payload live in the new parallel `source_payload_labels` tree alongside `source_payload`; the raw blob is never mutated. Consumers that hash `source_payload` for integrity continue to see the same hash.

### Reverse path

Operational rollback is not currently offered to consumers, but the inverse maps are documented in [ADR-0010](adr/0010-coded-fields-via-choicelist.md) and the rollback script lives at `scripts/reverse/us_s22_005c.py`. If a consumer needs a date range of historical state pre-2026-05-19, contact NSR Unit ops.

### Other notes from this slice

- New endpoint `GET /api/v1/reference-data/choice-list-bundle/` returns the active catalogue. Auth required. ETag = sha256 of canonical JSON. Cache-Control: private, max-age=60.
- `Household.dwelling_tenure` and `Household.residence_status` are now surfaced on the serializer with companion `_label` fields. They were previously absent from the response body.
- `Member` serializer companion `_label` fields shipped for: `relationship_to_head`, `sex`, `marital_status`, `nationality`, `residency_status`, `birth_certificate_status`, `nin_status`.
- Six Washington-Group disability dimensions (`seeing`, `hearing`, `walking`, `remembering`, `self_care`, `communicating`) currently render their raw payload codes — no label resolution until the `wg_disability` ChoiceList is seeded through the dual-approval workflow (`OI-S22-3`).

### Migration policy

The Django migrations (`0004_coded_fields_drop_textchoices` + `0005_coded_fields_to_choiceoption_codes`) are forward-only per ADR-0003. The reverse plan + inverse maps live in ADR-0010 §"Migration policy" and the rollback script. No production data has been lost — the rewrite is in-place and reversible.
