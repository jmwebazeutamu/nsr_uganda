# ADR-0009: DQA Rule Editor admin UI + write surface

- **Status**: Accepted
- **Date**: 2026-05-15
- **Owner**: NSR MIS Architecture Team
- **References**: SAD §4.2 (DAT-DQA), US-076 (Rule Editor UI), US-077 (preview), US-079 (operator set), CLAUDE.md "Tests first for any change touching DAT-DQA"

**Note on numbering**: The slice brief asked for "ADR-0005-dqa-rule-editor-ui". ADR-0005 is already taken by `sub-region-partitioning.md` (landed during Sprint 2 partition planning). This ADR therefore uses the next free number, 0009. The slice's intent — document the admin override, the new model fields, the operator additions, and the preview model — is preserved.

---

## Context

The DAT-DQA module shipped its engine, model, services, default admin, and read-only REST endpoints in Sprint 0. Sprint-N follow-up surfaced four gaps the operations team flagged during the threat-model workshop:

1. **Authoring rules is engineer-only today.** The admin renders the JSON-DSL expression as a raw textarea. Authors paste hand-written JSON; the engine raises `DSLError` at runtime if it's malformed, by which point a bad rule has already passed code review.

2. **No preview before activation.** Authors guess at impact. A rule that's too strict can quarantine thousands of intake records; a rule that's too loose lets bad data through. SAD §4.2 imagines a preview pane in the Rule Editor; nothing implements it.

3. **No audit on transition.** `services.py` mutates rule state but emits no `AuditEvent`. The SAD §8.4 promise that every personal-data-affecting decision is audited is paper-only for DQA. DPPA 2019 accountability fails on a regulator review.

4. **Half the SAD §4.2.3 operator catalogue is missing.** `within_polygon`, `accuracy_le`, `count_eq`, `count_neq`, `cross_field_eq`, `references_existing` are all referenced in rule packs we want to land but unimplemented in `apps/dqa/engine.py`.

---

## Decision

Land five commits in order on `us-076-077-079-dqa-rule-editor-ui`:

### DQA-1 — DqaRule lifecycle fields

Add three forward-only fields:
- `approval_note: TextField(blank=True)` — why a rule was approved.
- `rejection_reason: TextField(blank=True)` — why one was rejected.
- `submitted_at: DateTimeField(null=True)` — closes the lifecycle timestamp set.

Surface all three on `DqaRuleSerializer`. No service or test changes in this commit — the schema lands clean, DQA-2 wires persistence + audit against it.

### DQA-2 — services note/reason persistence + audit emission

Each service function:
- accepts an optional `actor: str` kwarg (defaults to the relevant rule field).
- persists `approve.note` / `reject.reason` into `DqaRule.approval_note` / `.rejection_reason`. Both required to be non-blank — `ApprovalError` raised on missing or whitespace-only.
- `submit_for_approval` stamps `DqaRule.submitted_at = timezone.now()`.
- emits one `AuditEvent` on success: `entity_type="dqa.rule"`, `entity_id=rule.id`, `action="dqa.rule_version.<verb>"`, `field_changes={before, after, ...note/reason/approver}`. `@transaction.atomic` ensures the audit write rolls back alongside any failure.

Mapping from the slice brief's vocabulary to the project's `AuditEvent` shape (no schema change needed):
- `target_type` → `entity_type`
- `target_id`   → `entity_id`
- `before_state`, `after_state`, `payload` → `field_changes`
- `timestamp` → `occurred_at` (auto-populated)

### DQA-3 — complete operator set

Implement the five missing operators in `apps/dqa/engine.py`:

| Operator | Shape | Notes |
|---|---|---|
| `accuracy_le` | leaf | Explicit semantic for GPS accuracy. Treats missing field as FAIL (not silent pass like `le`). |
| `count_eq` / `count_neq` | leaf | `len(field)` comparison. Strings count as scalars (not lists). |
| `cross_field_eq` | special leaf | Two fields from the same record. `{left_field, op, right_field}` — no `value`. |
| `references_existing` | leaf | Field value must resolve to a row in `app_label.ModelName`. Errors collapse to False (rule reports the data-quality failure, never crashes the pipeline). |
| `within_polygon` | leaf | Point-in-polygon, pure-Python ray-casting. **Deviation from the slice brief**: the brief said "use PostGIS GEOSGeometry"; we use a hand-rolled ray-cast instead. Rationale below. |

**Deviation: pure-Python point-in-polygon, not GEOSGeometry.** The DQA engine runs in-process per SAD §4.2.1; pulling `django.contrib.gis.geos.GEOSGeometry` into the rule evaluation path couples the engine to libgdal at the system level (the GEOS submodule's import cascade loads GDAL on first geometry construction). On the dev environment that does not have GDAL installed, the import fails outright. Production NITA-U deployment ships PostGIS so GDAL is available there, but the engine's design intent is to be backend-agnostic — rule evaluation should work the same on SQLite local dev as on Postgres production. The pure-Python implementation:

- Has zero non-stdlib dependencies.
- Handles the WKT POLYGON + POINT subset NSR rules need (single closed ring; no MULTI* yet).
- Uses ray-casting with PostGIS-compatible `ST_Contains` boundary semantics (point on boundary counts as inside).
- Is ~50 lines including parser. Uganda's sub-region boundaries are bounded by a few dozen vertices, so the asymptotic gap vs. GEOS is irrelevant.

If the engine ever needs the full PostGIS operator surface (intersections, buffers, ST_DWithin), this decision flips. Today it doesn't.

### DQA-4 — preview endpoint + `DqaRulePreviewRun` model

New endpoint `POST /api/v1/dqa/rules/{id}/preview/` with body `{sample_size, record_type}`. Returns `{pass_count, fail_count, sample_failed_record_ids[≤10]}`. Persists a `DqaRulePreviewRun` audit row (ULID PK, FK to rule, counts, IDs JSONField, executed_at, executed_by).

**Three privacy guarantees** baked into the endpoint shape:
- Response carries IDs only, never record values.
- Persisted run row carries the same IDs, never record values.
- Sample IDs capped at 10 regardless of `fail_count` (large failure sets don't bloat the run row beyond what an operator's eyes can use).

Sample selection uses a deterministic seed (`f"{rule.id}|{sample_size}|{record_type}"`) so tests get stable results and ops can re-run a preview against the same shape.

`record_type` is currently `member` or `household`; the dispatch table in `apps/dqa/api._preview_queryset` is the extension point for adding more.

### DQA-5 — custom Rule Editor admin UI + write endpoints

**Write endpoints.** `DqaRuleViewSet` promoted from `ReadOnlyModelViewSet` to `ModelViewSet`. Create/update gated by the new `IsDqaAuthor` permission class — checks for Django group `dqa_author` or superuser. Action endpoints (`submit-for-approval`, `approve`, `reject`, `retire`, `preview`) are *not* gated by group membership at the viewset level — the service layer's existing guards (cannot self-approve, cannot rule-jump states) carry that authorisation. DELETE intentionally absent; rules are retired, not deleted.

**Custom admin form.** `DqaRuleAdminForm` adds four `wizard_*` fields above the JSON textarea (`wizard_field`, `wizard_field_type`, `wizard_op`, `wizard_value`). On `clean()`, when the wizard fields are populated, the form compiles them into a leaf `{field, op, value}` JSON object and writes it to `DqaRule.expression`. The textarea remains the source of truth for composite (`all_of`/`any_of`) expressions — the wizard is opt-in.

Operator palette filtered by field type per the brief:

| Field type | Operators |
|---|---|
| string   | eq, neq, in, not_in, regex |
| numeric  | gt, lt, le, ge, between, accuracy_le, eq, neq |
| date     | between, gt, lt, eq, neq |
| geometry | within_polygon, accuracy_le |
| list     | count_eq, count_neq, in, not_in |
| boolean  | eq, neq |

Cross-type misuse (e.g. `within_polygon` on a numeric field) raises a `ValidationError` on save so authors get an early signal.

The form also runs the proposed expression through `evaluate_expression` against an empty record at save time, catching unknown operators / malformed all_of-any_of before the rule reaches production.

**Template override.** `apps/dqa/templates/admin/dqa/dqarule/change_form.html` extends `admin/change_form.html` and adds three panels below the form when `settings.DQA_RULE_EDITOR_V2` is on:

1. **Preview panel.** Record-type selector + sample-size input + Run button that POSTs to `/api/v1/dqa/rules/{id}/preview/` and renders pass/fail counts + failed IDs inline.
2. **Decisions panel.** Status-aware action buttons. DRAFT → "Submit for approval". PENDING → "Approve…" / "Reject…" — both open a `prompt()` modal demanding non-blank note/reason. ACTIVE → "Retire". Each posts to the matching action endpoint.
3. **Version history.** Table of every version sorted newest-first with author, approver, submitted/approved timestamps, approval note, rejection reason, and `difflib.unified_diff` against the prior version's expression JSON.

Tokens from `/design/v0.1/tokens.css` style the panels — active-rule status uses `--accent-quality` per the brief.

**Feature flag.** `settings.DQA_RULE_EDITOR_V2`, env-driven via `DQA_RULE_EDITOR_V2`. Default `True` when `DEBUG=True` (dev), `False` otherwise (prod gets an explicit env switch). When off, the admin falls through to the default Django change_form — operations can disable the new UI instantly without a deploy if a critical regression surfaces.

---

## Consequences

**Better.**

- Authoring rules without writing JSON. The wizard covers leaf rules (the 80% case); composites still get the textarea.
- Every rule transition leaves a tamper-evident audit row. DPPA 2019 accountability holds for DQA going forward; the regulator review surfaces the chain.
- Authors can preview a rule's impact without running it against the registry. The DqaRulePreviewRun table doubles as a longitudinal record of "what authors thought before activation".
- The five SAD §4.2.3 operators are no longer "to-do" comments in the engine docstring.

**Same.**

- Existing 27 DQA tests still pass without modification (per the slice brief constraint).
- The JSON expression on disk is unchanged — wizard is just a different way to author the same shape.
- DELETE still unavailable on rules (retire, don't delete — already the case).

**Worse.**

- Two surfaces for the same operation (wizard fields vs JSON textarea). Mitigation: the wizard is opt-in; when blank, the textarea wins. Clear docstring + help_text.
- The pure-Python `within_polygon` is one more thing to maintain. Mitigation: well under 100 lines, tests cover the WKT subset NSR rules use. If GEOS becomes mandatory (multi-polygon support, ST_DWithin, etc.) we flip the implementation — the operator's contract doesn't change.

---

## Test plan

```
pytest apps/dqa -v
```

Specifically:
- `TestLifecycleFields` (6 cases) — DQA-1 + DQA-2 field persistence and required-on-transition.
- `TestAuditEmission` (7 cases) — one event per transition, zero on failure.
- `TestAccuracyLe` / `TestCountOps` / `TestCrossFieldEq` / `TestReferencesExisting` / `TestWithinPolygon` — DQA-3 operators.
- `TestPreviewEndpoint` (5 cases) — DQA-4 counts, no-values, 10-cap, run row, 400 on unknown type.
- `TestWriteEndpoints` (8 cases) — DQA-5 role gate, action endpoints, self-approve block, audit count.
- `TestRuleEditorAdminSmoke` (3 cases) — change_form renders v2 panels when flag is on, omits when off, version diff renders.

OpenAPI spec at `/docs/openapi/dqa.yaml` updated with the new endpoints.

---

## Manual sanity check

From the project root, with `DQA_RULE_EDITOR_V2=1` and a Django admin login:

1. Create a `dqa_author` group; add user `alice` to it.
2. From `/admin/dqa/dqarule/add/`, alice authors a new rule via the wizard fields (e.g. `wizard_field=surname`, `wizard_op=not_null`).
3. From the change page, alice clicks "Run preview" — pass/fail counts render.
4. Alice clicks "Submit for approval".
5. User `bob` (also in `dqa_author`) opens the change page, clicks "Approve…", enters note "matches AC-MANDATORY".
6. Inspect `/admin/security/auditevent/` — two rows present: `dqa.rule_version.submitted_for_approval` (actor alice) and `dqa.rule_version.approved` (actor bob, field_changes contains note).
