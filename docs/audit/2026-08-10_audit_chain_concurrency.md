# F6 — HIGH — The audit hash chain forks under concurrent writes

**Date:** 2026-08-10
**Status:** open, not fixed
**Found:** while re-verifying the chain after an unrelated schema change (G2).

---

## What

`security_auditevent`'s `BEFORE INSERT` trigger builds the chain by reading the
current tail:

```sql
SELECT self_hash INTO latest_hash
  FROM security_auditevent
 ORDER BY occurred_at DESC, id DESC
 LIMIT 1;
NEW.prev_hash := latest_hash;
```

Two transactions that insert at the same moment both read the *same* tail
before either commits, so both chain to it. The chain forks: two rows share a
`prev_hash`, and one of them is not reachable by following the chain forward.

## Evidence

The chain was rebuilt to a verified-clean state on 2026-08-08 — 73,778 rows,
1 head, **0 forks**. Ordinary use since then (API calls, a runserver, the
compose web container and `manage.py` commands writing concurrently) added
~155 rows and produced:

```
total_rows 73,933 | heads 1 | dangling 0 | forks 23
mismatches 30, of which inside occurred_at ties: 0
gap to predecessor: min 0.49 ms, max 10.3 ms, all 30 within 1 second
```

Every forked row landed within **0.5–10 ms** of its predecessor. That is the
signature of concurrent inserts, not of the collation/tie problem fixed during
the sqlite→Postgres migration — those were all *inside* `occurred_at` ties;
these are all *outside* them.

## Why it matters

The hash chain is the registry's primary DPPA 2019 compliance artefact: it is
what makes the audit trail tamper-evident. A forked chain still detects
after-the-fact edits to individual rows, but it no longer supports the stronger
claim — that the log is a complete, ordered, unbroken record. An auditor
walking the chain from the head will not reach every row.

It is also silent. Nothing raises; the rows look fine individually. It only
appears if someone runs a structural verification.

At 12 million households with many concurrent operators, the rate will be far
higher than the ~19% of new rows seen on a nearly idle dev box.

## What it is not

Not the sqlite→Postgres migration artefact (that was collation-related, inside
`occurred_at` ties, and was fixed). Not caused by adding
`AuditEvent.purpose` — a new column does not enter the trigger's fixed payload.

## Options

1. **Advisory lock in the trigger** — `pg_advisory_xact_lock` on a constant, so
   chain appends serialise. Simplest correct fix; makes audit writes a
   serialisation point, which is a real throughput consideration at scale.
2. **A monotonic sequence column** as the chain order, with the tail read
   `FOR UPDATE`, so ordering is not derived from a timestamp that can tie.
3. **Accept per-row tamper-evidence and drop the total-order claim**, documented
   explicitly — the weakest option, and it needs the DPO to agree that is what
   §8.4 promises.

Option 1 or 2 needs an ADR: it changes the concurrency profile of every write
path that emits an audit event, which is all of them.

## Do not

Do not "repair" the chain by rebuilding it again. The rebuild used during the
migration is legitimate for a one-off import; running it against a live chain
would hide an active defect and rewrite hashes that an auditor may already have
seen.
