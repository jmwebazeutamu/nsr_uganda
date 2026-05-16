# DPIA — Sprint 16 Impact Recording

**Status**: For DPO review.
**Last updated**: 2026-05-15.
**Covers**: All stories merged to `main` during Sprint 16.
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

---

## Sprint 16 stories

### US-S16-001 — Audit-reason enrichment

- **New processing activity**: AuditReadMixin now lifts a narrow
  set of scope-narrowing and pagination query params into
  AuditEvent.reason (sub_region_code, household_id, entity_id,
  page, page_size). Same volume of audit rows; richer reason
  field.
- **Personal-data categories**: The added fields are query-param
  values, not personal data themselves. `entity_id` IS a
  Household/Member/etc. ULID — appears in the reason string. It
  was already in `entity_id` field of the AuditEvent in many
  paths; this story just makes it consistent on list endpoints
  too.
- **Lawful basis**: DPPA 2019 accountability requirement +
  internal audit policy (SAD §8.4).
- **Data minimisation**:
  - Five keys, not the full request.query_params. Other filter
    params (status=, category=, tier=) are business filters the
    operator legitimately uses; they're not what the DPO samples
    on. Adding them would just inflate the audit row.
  - When none of the five keys are present, the reason stays
    empty — common case for /retrieve/ and unfiltered /list/.
- **Residual risk**: None new. The audit row already carried
  the actor, action, entity_type, entity_id, IP, and user-agent;
  this story just adds the structured context the DPO actions
  from Sprints 14-15 explicitly asked for.

### US-S16-002 — Partner DRS "typical wait time"

- **New processing activity**: Presentation-only — partner-DRS
  portal eyebrow shows a client-side aggregate ("typical wait
  2.3d (n=8)") computed off `/requests/mine/` rows the partner
  already sees.
- **Personal-data categories**: Aggregate counts only. No new
  fields.
- **Lawful basis**: Public task — partner self-service per
  US-S7-004 + S9-005.
- **Data minimisation**: No new fetch, no new field exposure.
  Same MyDataRequestSerializer projection as S13-004.
- **Residual risk**: None new.

### US-S16-003 — Member endpoint max_page_size cap

- **New processing activity**: New `MemberPagination` subclass
  caps `?page_size=` at 100 on the Member list endpoint
  (vs the project-wide DefaultPagination cap of 500). Closes
  ADR-0008 OI-PAG-01.
- **Personal-data categories**: The capped endpoint exposes the
  highest-PII surface — encrypted NIN ciphertext, NIN last4,
  phone, DoB, sex, GPS via household FK.
- **Lawful basis**: Public task + DPPA 2019 minimum-necessary
  principle.
- **Data minimisation**: This story IS data minimisation. The
  500-row cap previously allowed several thousand PII fields
  per round-trip; 100 reduces enumeration blast radius 5×.
  Largest known Ugandan household (UBOS) is 26 members, so the
  100 cap doesn't constrain any legitimate consumer.
- **Residual risk**:
  - **Member listing remains a high-value enumeration target**
    despite the cap. The throttle (1000 req/min user default)
    and ABAC scope filter are the upstream defences. The cap
    is the inner ring. If telemetry shows a single operator
    hitting the Member endpoint at the cap repeatedly, the DPO
    should review.

### US-S16-004 — Audit chain integrity scheduled job

- **New processing activity**: New Celery beat task
  `verify_audit_chain_task` runs daily at 03:00 EAT. Walks every
  AuditEvent in chain order and verifies the prev_hash → self_hash
  linkage written by the Postgres trigger (migration 0002 from
  Sprint 0). Writes a `chain_integrity_verified` AuditEvent on
  success or `chain_integrity_break` on failure.
- **Personal-data categories**: The verifier reads only the
  chain hash columns and metadata (id, occurred_at). Does NOT
  re-read the actor, entity_id, reason, IP, or user-agent
  fields beyond what's needed for the break report. Break
  reports surface event_id + occurred_at (operationally needed
  to investigate) and capped at 5 break previews per row.
- **Lawful basis**: DPPA 2019 accountability + SAD §8.4 audit
  integrity claim. Until S16-004 this claim was paper-only —
  the trigger wrote the chain but nothing read it back.
- **Data minimisation**:
  - The verifier itself processes the whole table on each run,
    which is the smallest read that gives a complete answer.
    Incremental sweep (sample N most-recent) is an option for
    a future story if scan-time becomes a problem at national
    scale; today the full sweep is bounded by AuditEvent row
    count.
  - The `chain_integrity_verified` audit row carries only
    aggregate metadata (mode, rows_scanned, break_count). No
    PII.
  - The `chain_integrity_break` row's `field_changes` carries
    up to 5 break previews (event_id + occurred_at). Capped to
    bound row size; full list is in the celery task return
    value for the operator runbook.
- **Residual risk**:
  - **The verifier itself is a target**. A compromised celery
    process could emit fake `chain_integrity_verified` rows
    while skipping the real check. Mitigation: actor_kind
    "system" + actor_id "celery-beat" lets the DPO filter on
    those rows and cross-check with the worker logs.
  - **Detection latency is up to 24 hours**. Daily cadence is
    a deliberate trade-off — hourly would be more sensitive
    but the chain is large and rate-of-change is low. If the
    DPO needs faster, an on-demand admin action is a one-line
    follow-up (just call verify_audit_chain_task.delay()).
  - **SQLite dev backend** is silently "no_chain" — local
    developers don't get a chain check on their laptops. By
    design; the Postgres trigger is the chain source-of-truth
    and SQLite is a dev convenience only.

### US-S16-005 — DPIA Sprint 16 follow-up

- No new processing activity — documentation only.

---

## DPO action summary (delta from prior instalments)

| Action | Owner | Tied to |
|---|---|---|
| Confirm the five reason-enrichment keys (sub_region_code, household_id, entity_id, page, page_size) are sufficient for DPO sampling — recommend extending the list if not | DPO + Security | US-S16-001 |
| Spot-check Member endpoint reads against the new 100 cap — confirm 100 is comfortable headroom for legitimate roster consumers and not a real constraint | DPO + NSR Unit | US-S16-003 |
| Subscribe to `chain_integrity_break` audit rows via the anomaly feed; define escalation path on first occurrence (currently logged + audit row, no page) | DPO + Security | US-S16-004 |
| Decide whether daily 03:00 EAT chain verification cadence is acceptable, or move to hourly if regulator requires tighter detection latency | DPO + Compliance | US-S16-004 |

Plus the 42 actions still outstanding from prior instalments.

---

## Next review

Sprint 17 close. Sprint 17 candidate set:
- DDUP merge modal: surface live similarity scores in the
  confirm summary (currently shown on the compare table, not
  in the modal)
- Home dashboard: drill-down "back" affordance + breadcrumb
- DRS partner builder: real DSA-driven field disabling
  (currently mock per BUG-S11-002b)
- Slack/email alert wiring for `chain_integrity_break` events
  (currently logger.error + audit row only)
- DPIA Sprint 17 follow-up
