# US-130–131 — Rejected record lifecycle: retention and notification

**Status:** Proposed backlog addition
**Source:** Production review, 22 September 2026; SAD §4.6 (AC-DIH-REJECT-VOID); DPPA 2019
**Epic:** 16. Data Integration Hub

## Why these exist

`reject_stage_record()` sets the state, stamps `rejected_reason`,
`rejected_at` and `rejected_by`, writes a `PromotionDecision`, and emits
an audit event. What it does not do is decide what happens next — to the
data, or to the person.

Found while giving rejected records a screen (the DIH Rejected tab, 22
Sep 2026). Production then held **15 rejected stage records**, each
retaining its complete `canonical_payload`: every member, every answer,
NIN hashes and the last four digits, GPS to the metre. Nothing deletes
them, and nothing tells the household it was refused.

Neither is a regression. Both have been true since the module was
written, and neither is visible until you go looking — which is why they
are written down here rather than left as a comment.

---

## US-130 — Retain and dispose of terminal DIH records under a stated policy

**Priority:** Must
**Module:** DIH (ING), SEC
**Actor:** Data Protection Officer

As the Data Protection Officer, I want a stated, enforced retention
period for rejected and quarantined staging records, so that personal
data refused entry to the registry is not kept indefinitely without a
lawful basis.

### Context

- `apps/ingestion_hub/models.py` carries the only mention of a retention
  job — a comment saying one "lands when those callers are" built.
  Nothing schedules it.
- A rejected record keeps the full payload. The registry never accepted
  the household, so there is no registry entry to justify holding it.
- Quarantined records are in the same position; production has none
  today, which is exactly why the gap is easy to miss.
- DPPA 2019 requires personal data to be kept no longer than necessary
  for the purpose it was collected for.

### Acceptance criteria

- A retention period is defined per terminal state (rejected,
  quarantined) and recorded in an ADR with the DPO's sign-off.
- A scheduled job disposes of records past their period. Disposal is
  minimisation, not deletion of the audit trail: the `AuditEvent` chain,
  the `PromotionDecision` and the voided provisional ID survive, so the
  fact and the reason of the rejection remain provable after the personal
  data is gone.
- The payload is cleared in a way that cannot be undone by a database
  restore of the same row — disposal is recorded as its own audit event.
- A legal-hold flag exempts a record from disposal, for a grievance or an
  investigation in progress, and the hold is auditable.
- Records under the period are unaffected, and the Rejected tab keeps
  showing them.
- A dry-run reports what a run would dispose of before anything is
  written, and the first production run is executed that way.
- The policy covers records already past the period on the day it ships;
  the 15 on production today are the first cohort.

### Notes

Depends on a DPO decision about the period. Do not implement a default —
"90 days" chosen by a developer is the kind of number that ends up in an
audit finding.

---

## US-131 — Tell the source and the household when a submission is rejected

**Priority:** Must
**Module:** DIH (ING), GRM
**Actor:** Household respondent / Source Admin

As a household whose registration was refused, I want to be told that it
was refused and why, so that I can correct the record or raise a
grievance instead of waiting indefinitely for an outcome that will never
come.

### Context

`reject_stage_record()`'s own docstring states the requirement and its
absence: *"Voids the provisional ID; the citizen or source must be
notified with a reason (notification path lands separately)."* That path
was never built.

Of the 15 rejections on production, most are bulk duplicate clears by
`ops-backfill`, but several are human decisions taken in the console
("Duplicate of existing registered household", "Other (specify in
note)"). Nobody outside the NSR Unit knows they happened.

A refusal the subject cannot see is also a refusal they cannot contest,
which undermines the grievance route the registry is supposed to offer.

### Acceptance criteria

- Rejecting a record queues a notification to the household contact
  number of record (ADR-0033) where one exists, and to the source system
  owner for machine-originated submissions.
- The message carries the reason in plain language and the grievance
  route. It never carries a NIN, a provisional ID or any other
  identifier useful to someone who intercepts it.
- Bulk and administrative rejections are distinguishable from
  case-by-case ones, and the notification policy for each is explicit:
  a duplicate clear-down should not send 10,000 messages.
- Where there is no contact number, the omission is recorded on the
  record and visible on the Rejected tab, so "not notified" is a fact
  somebody can see rather than silence.
- Delivery success and failure are auditable; a failed send is retried
  under a stated policy and surfaces to an operator when it finally
  fails.
- Consent for transactional messaging is respected per ADR-0031.

### Notes

Depends on the SMS sender already specified in ADR-0031/ADR-0033. GRM
needs to accept a grievance that references a rejected stage record,
which no longer has a registry entry to hang off.
