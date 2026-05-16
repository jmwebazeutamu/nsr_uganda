# US-082 — DQA rule-violations dashboard

**Epic:** 2. Data Quality (DAT-DQA). Follow-up to US-076 / US-077 / US-079.
**Module owners:** apps/dqa, apps/ingestion_hub, apps/reporting.
**Status:** Not started.
**Filed:** 2026-05-15 (mid-session, during DQA Rule Editor branch).
**Sibling open story:** US-080 (re-run rules on UPD re-save) — independent, scheduled separately.

## Why

Today the DQA pipeline evaluates every rule against every staged
record (`apps/ingestion_hub/services.py:_dqa_inline`), but the failures
land in `StageRecord.dqa_summary` (a per-record JSON blob) — there
is no aggregate view of "which rules are failing most often." The
`apps.dqa.models.DqaResult` table exists with the right indexes
(`passed`, `severity`, `record_type`) and an `evaluate.to_result()`
helper, but **nothing currently persists rows into it** (0 rows in
the dev DB; expected to be 0 in prod too).

That gap stops the System Admin and the field-collection lead from
answering the question that drives data-collection improvement:

> "Which fields are most commonly invalid? What should we train
>  enumerators on next week?"

## Stories

### US-082a — Persist DqaResult rows from DIH inline evaluation

**As a** System Admin
**I want** every blocking/warning DQA failure recorded as a row in
`DqaResult`
**So that** we can aggregate by rule, severity, severity-band, and
sub-region.

**Acceptance criteria:**
- `_dqa_inline` in `apps/ingestion_hub/services.py` writes one
  `DqaResult` per *failed* evaluation (skips passes — keeps the
  table 90% smaller). Severity = the rule's declared severity.
- `record_type` is the actual entity ("household" or "member"),
  `record_id` is the provisional registry id or
  `<provisional_id>:<line_number>` for members.
- Severity=`info` is excluded by default; ops can re-enable via
  `DQA_PERSIST_INFO_FAILURES=true` if the registry needs it.
- Writes are bulk_create(batch_size=100) so 50-member households
  don't paper-cut the DB.
- New unit test confirms a staged record with 2 failing rules
  writes exactly 2 DqaResult rows.

### US-082b — RPT dashboard endpoint

**As an** NSR Unit Coordinator (or DQA Author)
**I want** a `GET /api/v1/rpt/dashboards/dqa-violations/` endpoint
**So that** I can see the top-N most-failed rules over a recent
window.

**Acceptance criteria:**
- Query params: `window=7d|30d|all` (default `7d`),
  `severity=blocking|warning|info|all` (default `all`),
  `entity=member|household|all` (default `all`),
  `sub_region_code=<code>` (optional, narrows via Household join
  per the US-S15-003 drill-down pattern).
- Response: `[{rule_id, rule_label, severity, fail_count,
  fail_rate, last_seen_at}, ...]` sorted by `fail_count` desc.
  `fail_rate` is `fail_count / total_evaluated_records` in the
  same window — gives the operator denominator context.
- ABAC-scoped via `scope_q_for_field` on Household, same pattern
  as `OperatorKpisView`.
- One `AuditEvent` emitted per call via `AuditReadMixin`-style
  emission (we don't have a mixin for APIViews; reuse
  `emit_audit` directly).
- Pagination follows ADR-0008 (DefaultPagination, default 50, cap
  500).
- Tests: superuser sees all; sub-region-scoped op sees narrowed
  counts; out-of-scope drill-down returns zeros not 403.

### US-082c — Admin changelist column on DqaRule

**As a** DQA Author opening `/admin/dqa/dqarule/`
**I want** a `failures_7d` column on the rule list
**So that** I can spot at-a-glance which rules are firing most.

**Acceptance criteria:**
- New computed column on `DqaRuleAdmin.list_display`.
- Sortable. Numeric. Renders as "1,284 (1.2%)" — count + rate.
- Cheap to render: pulls from the same materialised aggregate the
  dashboard uses (US-082d below) — no per-row query.
- Hover/title tooltip shows the breakdown by severity if mixed.

### US-082d — Optional Celery aggregator (open item)

**Decide during US-082b design:** at 12M households × 30 rules =
360M rows/month in `DqaResult`. Two paths:

- **Path A — live aggregation**: dashboard queries `DqaResult`
  directly with a `Count(case)` over the window. Simple. Works
  fine to ~50M rows. Above that, the dashboard latency climbs.
- **Path B — materialised aggregate**: nightly Celery beat task
  computes a `DqaViolationDaily(rule, date, fail_count,
  total_evaluated)` table. Dashboard reads the materialised
  table. Daily-resolution; the per-record `DqaResult` still
  exists for forensic drill-down.

Recommendation: ship Path A in US-082b, add Path B as a follow-up
only if dashboard p95 > 1s at the projected scale. Keep US-082b
service-layer interface small enough that the swap is invisible
to consumers.

## Non-goals
- Rendering this on the React home dashboard. Operators triage
  through the existing queue panels; the violations dashboard is
  a DQA-author/admin tool, lives in `/admin/` first. React surface
  is a follow-up if demand emerges.
- A separate "trend over time" view. RPT's existing
  comparative-dashboards story (US-S11-007) is the model; this
  story stays a single-point top-N for the chosen window.

## Definition of Done

- `pytest apps/dqa apps/ingestion_hub apps/reporting -v` all green
  including new tests for US-082a / US-082b / US-082c.
- OpenAPI at `/docs/openapi/dqa.yaml` (or a new `rpt.yaml`)
  updated with the new endpoint.
- ADR if Path B is chosen at US-082b time (decision rationale +
  rollout plan).
- Manual sanity check: from `/admin/dqa/dqarule/`, the System
  Admin sees the new `failures_7d` column. Hitting
  `/api/v1/rpt/dashboards/dqa-violations/?window=7d` returns the
  same top rule with the same count.

## Tradeoffs / open questions

- **Write volume at intake scale.** See US-082d. Default to
  failures-only (Path A) and re-evaluate if telemetry warrants.
- **Rule deactivation churn.** Retired rules still have historical
  failures. Dashboard should join through `DqaRule.rule_id` not
  `DqaRule.id` so retired versions still show their lifetime tally.
- **Per-field vs per-rule.** Field-level "which questionnaire
  question fails most" is what the field-collection lead actually
  wants. Today the engine doesn't surface "the field that caused
  the failure" beyond what the rule's `error_message_template`
  renders. Adding a structured `failing_field` column to
  `DqaResult` is a separate (smaller) extension; deferred from
  this story to keep the scope tight. **Open item to revisit
  before US-082b ships** — if `failing_field` is cheap to derive
  from the engine, it pays back ten times in the dashboard.
