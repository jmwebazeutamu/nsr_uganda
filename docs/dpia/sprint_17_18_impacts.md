# DPIA — Sprint 17 + 18 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprints 17 and 18.
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

**Note on cadence**: Sprint 17 closed without a standalone DPIA
instalment — the violations dashboard work happened ad-hoc mid-
session in response to an operations question. This instalment
folds Sprint 17 in alongside Sprint 18 to restore the per-sprint
record without backdating a separate file.

---

## Sprint 17 stories (US-082 sub-sprint)

### US-082a — Persist DqaResult rows from DIH inline evaluation

- **New processing activity**: Every failed DQA evaluation from the
  DIH staging pipeline now writes a row to the `DqaResult` table.
  Previously the engine returned `Evaluation` objects that
  surfaced into `StageRecord.dqa_summary` (JSON blob) but the
  aggregate-friendly `DqaResult` table — present in the schema
  since Sprint 0 — was never populated.
- **Personal-data categories**: `DqaResult` rows store:
  - `rule` FK
  - `record_type` ("household" or "member")
  - `record_id` — the household ULID or `"<hh_ulid>:<line>"` for
    members
  - `passed` (always False — we only persist failures)
  - `severity`
  - `reason` (the rendered error message from
    `error_message_template`)
  - `executed_at`
  No NIN, no name, no GPS, no phone is stored in the DqaResult
  row itself. The `reason` field may render a value via the
  rule's error template (e.g. "NIN format invalid: CMABC123…"),
  so the rendered string CAN leak a partial field value — same
  exposure that already lives in `StageRecord.dqa_summary`.
- **Lawful basis**: Public task + DPPA accountability — failures
  must be auditable so the registry can demonstrate how data
  quality is enforced.
- **Data minimisation**:
  - Failures only. Passes are not persisted. At a default 30-rule
    pack and a typical 5-failure rate per staging, this cuts the
    table size 90% vs writing every evaluation.
  - `info` severity is excluded by default (set
    `DQA_PERSIST_INFO_FAILURES=True` if the registry needs them).
  - `bulk_create(batch_size=100)` keeps per-stage write cost flat.
- **Residual risk**:
  - **`reason` text may render PII via the rule template**. The
    same exposure already exists in `StageRecord.dqa_summary`,
    so this story doesn't change the surface — but it spreads
    the same data to a table the violations dashboard reads.
    Mitigation: rule authors should avoid templates that
    interpolate raw PII. The DQA Rule Editor (US-076) doesn't
    enforce this yet — flag for a future hardening pass.
  - **Bulk-create skips per-row signals**. AuditEvent is NOT
    emitted per DqaResult write (a single staging fires N
    DqaResult inserts but only one StageRecord audit). DPO
    sampling sees the staging-level audit and can derive
    failure counts from the DqaResult table; per-row read events
    happen when the dashboard queries.

### US-082b — RPT violations dashboard endpoint

- **New processing activity**: New `GET
  /api/v1/rpt/dashboards/dqa-violations/` aggregator. Returns
  `[{rule_id, rule_label, severity, fail_count, last_seen_at},
  …]` sorted desc.
- **Personal-data categories**: Aggregate counts only. No record
  IDs are returned. No `reason` strings.
- **Lawful basis**: Public task — operational reporting.
- **Data minimisation**:
  - Response shape is intentionally rule-grained, not
    record-grained. An operator who wants to investigate a single
    rule's failures can drill into Django admin
    `/admin/dqa/dqaresult/` (already gated by `is_staff`).
  - ABAC scope via Household join: a sub-region operator's
    counts include only failures whose `record_id` resolves
    back to a Household in their scope. Orphan failures (from
    legacy/preview-style `_evaluate_dqa` calls without a
    `stage_id`) are invisible to scoped operators by
    construction.
  - Audit-reason enrichment (US-S16-001) records `window`,
    `severity`, `sub_region_code` from the query string into
    `AuditEvent.reason` for structured sampling.
- **Residual risk**:
  - **Endpoint reveals which rules fail most often, which is
    weakly an insight into where DATA QUALITY is worst**. An
    attacker who can authenticate to the dashboard could infer
    which questionnaire fields are unreliable — useful for
    crafting plausible-looking fake intake. The mitigation is
    role-gating (currently `IsAuthenticated`; consider tightening
    to NSR Unit or DPO if telemetry shows broad access).

### US-082c — `failures_7d` column on DqaRule admin changelist

- **New processing activity**: `DqaRuleAdmin.list_display` adds
  a sortable column showing the 7-day failure count per rule.
- **Personal-data categories**: Same as US-082b — aggregate
  count only.
- **Lawful basis**: Public task.
- **Data minimisation**: Column is on the `/admin/dqa/dqarule/`
  list, gated by `is_staff`. Single annotated query, no per-row
  fetch.
- **Residual risk**: None new. Same admin gate as the rest of
  DqaRuleAdmin.

---

## Sprint 18 stories

### US-S18-001 — DDUP merge modal per-field similarity

- **New processing activity**: Presentation change inside the
  merge confirm modal. Surfaces the matcher's per-field
  similarity scores (already computed by the DDUP engine,
  already displayed on the side-by-side compare table) inside
  the modal as well.
- **Personal-data categories**: Scores only — no field VALUES.
  Operator already sees the values on the compare table behind
  the modal.
- **Lawful basis**: Public task.
- **Data minimisation**: No new fetch, no new field; mirrors
  what's already on screen.
- **Residual risk**: None new. Slightly higher cognitive surface
  in the modal, but that's the intent — the operator needs the
  evidence trail when they commit a merge.

### US-S18-002 — Home dashboard drill-down breadcrumb

- **New processing activity**: Banner under the page header when
  a sub-region drill-down is active. Pure UI; same data the
  dashboard already shows.
- **Personal-data categories**: None.
- **Lawful basis**: Public task.
- **Data minimisation**: N/A. Banner only renders the chosen
  sub-region name, which the operator picked from the selector
  one click earlier.
- **Residual risk**: None.

### US-S18-003 — DRS partner builder DSA-driven field disabling

- **New processing activity**: The partner DRS query builder
  now fetches `/api/v1/drs/requests/builder-schema/` (BUG-S11-
  002a) and honours its `disabled` / `disabled_reason` flags.
  Previously the screen used a static mock with hardcoded
  disabled fields, so a partner could THINK they were
  authoring against the real DSA while actually editing a
  preview.
- **Personal-data categories**: The endpoint response includes
  the DSA's `allowed_scopes.fields` set — which fields ARE
  permitted under the partner's DSA. No PII, but it does
  enumerate the schema.
- **Lawful basis**: Public task + the partner's DSA.
- **Data minimisation**:
  - Endpoint already shipped per BUG-S11-002a. This story is
    just a wiring change in the React layer.
  - Disabled flags come from `DsaSerializer.allowed_scopes` —
    same source the DRS submit-time validator already uses.
    Tightening the UI to match the validator closes a known
    bug ("partner can configure a request that will be
    rejected at submit").
- **Residual risk**:
  - **Field enumeration**. An authenticated partner can see the
    list of fields THEY don't have access to (with the
    DSA-issued reason). That's intentional — they need to know
    what to request an expansion for. The DPO Action below
    pins a follow-up to confirm this listing depth is acceptable.

### US-S18-004 — Slack + email alerts on `chain_integrity_break`

- **New processing activity**: `verify_audit_chain_task`
  (US-S16-004) now fires out-of-band notifications when a chain
  break is detected.
  - Slack: incoming-webhook payload with break count + first
    event id. Full record stays on the AuditEvent.
  - Email: `send_mail` to `settings.DPO_EMAIL` with a 5-event
    summary.
- **Personal-data categories**: Break payload contains
  `AuditEvent.id` (a ULID) and `occurred_at`. No actor name, no
  reason string, no IP. The Slack/email message is therefore
  metadata-only.
- **Lawful basis**: Public task + DPPA 2019 §27 (notification of
  data-integrity incidents).
- **Data minimisation**:
  - Up to 5 event ids in the email body; 1 in the Slack payload.
    The full break list stays on the AuditEvent.
  - Both channels default to no-op when their setting is empty.
- **Residual risk**:
  - **Slack channel hygiene**. The webhook URL is a shared
    secret; rotating it requires an env update + service
    restart. Should be in the operations rotation list, not in
    a long-lived `.env` file.
  - **Email channel deliverability**. Django's default email
    backend writes to console in dev; production needs an
    actual SMTP backend configured. Verify before relying on
    email-only alerting.

### US-S18-005 — DPIA Sprint 17 + 18 follow-up

- No new processing activity — this document.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm `DqaResult.reason` rendering doesn't expose more PII than `StageRecord.dqa_summary` already does; flag any rule templates that interpolate raw NIN / DoB / phone | DPO + DQA Author | US-082a |
| Decide whether `dqa-violations` dashboard should be tightened from `IsAuthenticated` to `IsDqaAuthor` or NSR Unit role; current default is open to any logged-in user | DPO + Security | US-082b |
| Confirm partner-side field enumeration depth (showing disabled fields + DSA-issued reason) is acceptable; alternative is omitting disabled fields entirely from the partner's view | DPO + Partner Liaison | US-S18-003 |
| Add the Slack webhook URL to the secrets-rotation rota | Ops + Security | US-S18-004 |
| Configure production SMTP backend for chain-break email alerts; verify deliverability with a test break in staging | Ops | US-S18-004 |

Plus the 46 actions still outstanding from prior instalments.

---

## Next review

Sprint 19 close. Sprint 19 candidate set (from in-conversation
deferred items):
- US-080 — re-run rules on UPD re-save (already filed; not yet
  scheduled)
- US-081 — CAPI rule pack publication
- US-082d — Celery materialised aggregate for DqaViolationDaily
  (only if dashboard latency telemetry warrants)
- US-116 → US-120 — Questionnaire authoring epic (per the
  long-form story under docs/stories/)
- DPIA Sprint 19 follow-up
