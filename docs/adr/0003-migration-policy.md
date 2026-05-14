# ADR-0003: Migration policy — reversible through Sprint 5, forward-only thereafter

- **Status**: Accepted
- **Date**: 14 May 2026
- **Owner**: NSR MIS Architecture Team
- **References**: SAD v0.6 §11.5 (Definition of Done), §3.3, ADR-0001

---

## Context

The NSR MIS owns the audit-bearing system of record for 12 million households. Schema changes that break the audit chain, drop a version row, or strand a foreign key are not just bugs; they break the legal defensibility of the registry under DPPA 2019.

Two competing pressures shape the migration policy:

1. **Early in the project**, schema churn is high. Modules find better names, better relations, better partitioning strategies during Sprint 0 through Sprint 4. The team needs the freedom to undo a migration that turned out wrong.
2. **Once the registry holds real data**, reversibility becomes dangerous. A "down" migration on a populated table is rarely safe; it usually involves data loss, broken triggers, or stale audit pointers. Production migrations need to be additive and forward-only.

We also run on PostgreSQL 16 with declarative partitioning by sub-region, which makes certain `ALTER TABLE` operations slow or disruptive. The migration tool of record is Django migrations, with optional raw SQL escape hatches in `data_management` and `ingestion_hub` (per CLAUDE.md).

## Decision

We adopt a **two-phase migration policy** keyed to the development phase:

### Phase 1: Sprint 0 through Sprint 5 — reversible

Every migration ships with a working `Migration.backwards()` / `reverse_sql`. Reversibility is enforced by CI: a job applies the migration, then immediately runs the reverse, then re-applies, and the test suite must pass at each step. This catches "down" migrations that look reversible but are not.

- Schema changes are free during this phase.
- Data migrations (anything inside `RunPython`) must also be reversible.
- The reversibility CI job runs against a fixture-loaded database, not an empty one, so reversibility against real shapes is exercised.
- The team is allowed to squash migrations at the end of Sprint 5, but only after a green run of the reversibility job.

### Phase 2: Sprint 6 onwards — forward-only with a reverse plan

Once the staging environment holds production-equivalent data and partner integrations have started, migrations become forward-only. Each release ticket attaches a **reverse plan**, which is a written document, not code.

The reverse plan covers:

1. **What changes** (the migration's diff in plain English).
2. **How to roll back** if the change is bad. This is usually a forward migration that restores the prior shape, not a reversed Django migration. Adding the column back is a new migration, not running `migrate <app> <prior>`.
3. **What data, if any, is lost** if the rollback is run after some live writes have happened on the new schema. If the answer is "real data", the change is staged behind a feature flag and the cut-over happens after the flag has been on long enough to verify.
4. **Who approves the rollback** during an incident.

Forward-only does not mean "irreversible". It means "we do not rely on Django's `migrate` reverse machinery to handle it". The reverse is engineered, reviewed, and tested separately.

### Operating rules in both phases

- **Migrations are blue-green compatible.** Every schema change must work with both the prior application version and the next. Renames are split into three steps (add new column, dual-write, drop old column) across at least two releases.
- **No destructive operations in a single migration with the application change that uses it.** Dropping a column happens at least one release after the code that stopped reading it.
- **Partitioned tables** (Household, Member, Submission, AuditEvent) use migrations that detach a partition, alter it, and re-attach. Never `ALTER TABLE` directly on the parent in production.
- **Index creation in production uses `CREATE INDEX CONCURRENTLY`** wrapped in a non-atomic Django migration (`atomic = False`). The reversibility CI job has an exception for this.
- **Long-running data backfills** run as Celery jobs, not as `RunPython`. The migration only adds the column and the trigger; the backfill is a separate, observable job with progress reporting.
- **Schema version metadata** is written to a `schema_versions` table on every migration apply, with timestamp, git SHA, applied-by user, and a hash of the SQL executed. This is queryable by support without reading the migration files.
- **Migrations cannot drop AuditEvent rows.** Period. The audit chain is immutable. If a column on AuditEvent needs to change, add a new column; do not drop or alter the old one.
- **Migrations cannot drop HouseholdVersion or MemberVersion rows.** Same reason: the as-of-date query depends on them.

### Definition of Done (per migration)

A migration is "done" when:

1. The migration file is committed with a clear name describing the change.
2. The reversibility CI job is green (Phase 1) OR the reverse plan is attached to the release ticket (Phase 2).
3. The migration was applied locally on a fixture-loaded database without errors.
4. If the migration touches an audit-bearing table (Household, Member, *Version, AuditEvent, ChangeRequest, MergeDecision, PromotionDecision), it has been reviewed by two engineers, not one.
5. The blue-green compatibility note is in the commit message ("compatible with vN and vN+1").
6. For Phase 2 migrations, the reverse plan is filed in `/docs/runbooks/migration-reverse-plans/{release}.md`.

## Consequences

### Positive

- **Fast iteration in Phase 1.** Engineers can reshape schemas without fear of breaking production. The reversibility CI gate catches mistakes early.
- **Safe production schema evolution in Phase 2.** Forward-only plus blue-green plus engineered reverses means a bad release can be rolled back without data loss.
- **Audit chain integrity.** AuditEvent, HouseholdVersion, MemberVersion are protected from accidental drops.
- **Operational observability.** The `schema_versions` table gives support staff a single place to ask "what version is this database at?" during an incident.
- **Partner stability.** Once we are forward-only, partner integrations do not break under us because of a rolled-back migration.

### Negative / costs

- **Phase 1 reversibility CI is slow.** Apply, reverse, re-apply, run tests adds 3 to 5 minutes per PR. Mitigation: cache the post-fixture database state and reset between steps; parallelise where possible.
- **Phase 2 reverse plans add ceremony.** Every release touching the schema needs a one-page document. Mitigation: a `runbook` template lives in the repo; most reverses are short.
- **Three-step renames slow column refactors.** Mitigation: rename only when meaningful; not for cosmetics.
- **Index `CREATE CONCURRENTLY` outside the migration's atomic block** is a footgun if the engineer forgets the wrapper. Mitigation: a lint rule in CI catches `CREATE INDEX` not inside an `atomic = False` migration in `data_management` or `ingestion_hub`.

### Risks accepted

- **A bad Phase 2 migration with no reverse plan attached** could be merged if review is sloppy. Mitigation: CI rejects the PR if the release ticket reference does not link to a `migration-reverse-plans` file.
- **Forward-only does not protect against logic bugs.** A migration that copies data into a new column wrong cannot be undone by a reverse plan; the data is lost. Mitigation: feature-flag the read path so the system continues to read the old column until the new one is verified.

## Alternatives considered

### A. Always reversible

Rejected. False sense of safety. A reverse of a populated table is rarely correct under concurrent writes. The reversibility tool is genuinely useful only on small databases without real users.

### B. Forward-only from day one

Rejected. Phase 1 schema churn would slow to a crawl. Reverse plans for every PR during Sprint 0 are wasted ceremony when no production data is at risk.

### C. Schema-as-code via a dedicated tool (Atlas, sqitch, dbmate)

Considered. These tools are good. Rejected for now because Django migrations are the team's idiom, the framework support is mature, and introducing a parallel tooling track for the same problem is overhead without a clear win at our scale. Re-evaluate if Django migrations show their limits under partitioned-table churn.

### D. No partitioning until Phase 2

Rejected. Partitioning is locked in the SAD for read locality at the parish operator level. Introducing partitioning later would require a full data move on a populated 12M-row table. Pay the cost up front.

## Compliance

- DPPA 2019: schema integrity supports accuracy and accountability obligations. Audit trail preservation is non-negotiable.
- SAD §11.5 Definition of Done.
- SAD §8.4 audit and observability.

## Re-open triggers

1. Sprint 5 ends. The policy switches automatically; no decision needed, but a checkpoint review is required.
2. The reversibility CI job exceeds 8 minutes on a steady-state PR. Either optimise or relax the policy.
3. A migration tool other than Django migrations becomes the team's preference (would require ADR-0010 superseding the tool choice).
4. A partner integration introduces a schema dependency we did not anticipate (would force a tighter compatibility rule).

---

End of ADR-0003. Place at `/docs/adr/0003-migration-policy.md`.
