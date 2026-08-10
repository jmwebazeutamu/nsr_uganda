# ADR-0029: Serialising audit-chain appends

- **Status**: Accepted
- **Date**: 10 August 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Engineering Lead
- **References**: SAD §8.4 (audit — hash-chained, append-only); ADR-0003 (migration policy); `docs/audit/2026-08-10_audit_chain_concurrency.md` (F6); `apps/security/migrations/0002_auditevent_chain_trigger.py`, `0009_audit_chain_head.py`

---

## Context

`AuditEvent` is hash-chained by a `BEFORE INSERT` trigger: each row stores the
previous row's `self_hash` and its own hash over `prev_hash || payload`. SAD
§8.4 relies on that chain to make the audit trail tamper-evident.

The trigger found its predecessor by scanning the event table:

```sql
SELECT self_hash INTO latest_hash
  FROM security_auditevent
 ORDER BY occurred_at DESC, id DESC LIMIT 1;
```

Two transactions inserting at the same moment both read the same tail before
either committed, and both linked to it. The chain forked: two rows shared a
`prev_hash`, and one branch became unreachable when walking forward from the
head.

Measured on the dev database: a chain rebuilt to **0 forks** on 2026-08-08
accumulated **23 forks over ~155 rows** of ordinary use — every forked row
landing within 0.5–10 ms of its predecessor. Nothing raised. The rows look
individually valid; only a structural walk reveals it.

At national scale, with many concurrent operators, the rate would be far higher
than on a nearly idle development box.

## Decision

### D1. The chain tail lives in its own single row, and appenders lock it.

`AuditChainHead` holds `last_hash`. The trigger takes a row lock on it, reads
the current value, links the new row to it, and updates it.

### D2. Lock with `INSERT … ON CONFLICT DO UPDATE … RETURNING`, not an advisory lock.

**An advisory lock does not fix this**, which a concurrency test demonstrated
before this ADR was written: with `pg_advisory_xact_lock` in place, eight
concurrent writers still produced 5 forks.

The reason is snapshot isolation, not locking. In READ COMMITTED a query inside
a trigger runs with the snapshot of the **calling statement**, taken before the
trigger body executes. A second inserter could therefore wait for the advisory
lock, acquire it, and still read a tail from before the first transaction
committed.

`SELECT … FOR UPDATE` is the documented exception: a waiter re-reads the latest
committed version of the row once the lock is released. `INSERT … ON CONFLICT
DO UPDATE … RETURNING` gives the same fresh-read-under-lock **and** recreates
the row if it is absent, so truncation (which the test runner does) cannot
leave the chain pointing at a hash that no longer exists.

### D3. The hashed payload is unchanged.

Byte-for-byte the columns hashed since migration 0002. Only the tail lookup
changed. Altering the payload would recompute the formula for every row and
invalidate all 73,933 existing `self_hash` values.

### D4. Existing forks are not repaired.

The 23 forks already in the chain stay. Rewriting hashes on a live chain would
hide an active defect and invalidate anything an auditor has already verified.
They are evidence of a period during which the guarantee did not hold, and the
honest record is to leave them and say so.

*(The one-off rebuild during the sqlite→Postgres migration was different: an
import, before the data was live, where no auditor had seen anything.)*

## Consequences

**Good.** The chain is a single ordered list again, and a structural walk from
the head reaches every row. Pinned by a real-concurrency test — eight threads
on separate connections — which is the only kind that can catch this; the
defect survived 73k rows because every existing test was single-threaded.

**Cost: audit appends serialise.** Every write path emits audit events, so this
is a global serialisation point. It is inherent to maintaining one ordered
chain — the alternative is to give up the total-order claim.

**Cost: the lock is held until the transaction ends.** A long transaction that
emits an audit event early blocks other audit writes for its whole duration.
Acceptable here because the write paths are atomic *per unit of work* —
`recompute_for_household` wraps one household, promotion wraps one record — so
a national batch is millions of short transactions rather than one long one.
**A genuinely long-running transaction that needs to emit audit events should
emit them in a separate short transaction rather than lengthening this lock.**

**Watch.** If audit-append contention ever shows up in latency, the next step
is a per-partition chain (one per sub-region, matching ADR-0005) rather than
weakening the guarantee — that trades one global chain for N independent ones,
each still totally ordered.

## Alternatives considered

**Advisory lock alone.** Rejected — measured insufficient (D2). Worth recording
because it is the obvious first answer and it silently does not work.

**SERIALIZABLE isolation.** Correct, but pushes retry loops into every write
path in the system.

**Asynchronous sealing** — insert rows unchained, chain them in a
single-threaded job. Removes contention from the write path entirely, at the
cost of a window in which rows are not yet tamper-evident. Worth revisiting if
D1's serialisation becomes a real bottleneck; it changes what §8.4 promises, so
it needs the DPO.

**Accept forking and narrow the §8.4 claim** to per-row tamper-evidence.
Rejected: the completeness claim is most of the value to an auditor, and giving
it up should not happen by accident.
