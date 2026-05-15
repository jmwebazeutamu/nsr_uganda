# ADR-0005: Sub-region declarative partitioning for Household and Member

- **Status**: Accepted (Sprint 1: key + design landed; cut-over deferred to Sprint 2)
- **Date**: 2026-05-15
- **Owner**: NSR MIS Architecture Team
- **References**: SAD v0.6 §5.5 (Indexing and partitioning), ADR-0001, ADR-0003

---

## Context

Per SAD §5.5 the Household and Member tables are declared "PostgreSQL
declarative partitioning by sub-region (9 partitions), aligned with read
locality for parish operators and field operations."

At full national scale we expect ~12M households and ~50M members.
Partitioning by sub-region gives us three properties the SAD relies on:

1. **Read locality.** A Parish Chief query is naturally scoped to their
   sub-region; the planner can prune 8 of 9 partitions for free.
2. **Operationally manageable indexes.** Per-partition indexes top out at
   ~1.4M rows for Household instead of 12M; rebuilds and vacuums are
   feasible during the maintenance window.
3. **Partition-aware archival.** A sub-region whose registry has matured
   can be moved to slower storage without touching the others.

ADR-0003 §C explicitly rejects "no partitioning until Phase 2" because
moving a populated 12M-row table is the expensive failure mode we are
trying to avoid. The window to introduce partitioning is **before** any
bulk-load story executes.

## Decision

Adopt **PostgreSQL declarative LIST partitioning** of `data_management_household`
and `data_management_member` by a denormalised `sub_region_code` column.

The 9 partitions match the SAD's sub-region taxonomy:

| Partition | Sub-region |
|---|---|
| `..._central` | Central (Buganda North, Buganda South, Kampala) |
| `..._eastern` | Eastern (Bukedi, Busoga, Bugisu, Sebei) |
| `..._northern` | Northern (Acholi, Lango, West Nile) |
| `..._karamoja` | Karamoja |
| `..._western` | Western (Tooro, Ankole, Kigezi, Rwenzori) |
| `..._teso` | Teso |
| `..._bunyoro` | Bunyoro |
| `..._unassigned` | DEFAULT — catches rows without a sub_region_code |

Sub-region taxonomy follows the UBOS administrative hierarchy already
loaded in `apps.reference_data.GeographicUnit`. The partition count is
fixed at 9 because the field-operations geography is fixed.

### Sprint 1 — what landed in this ADR

1. New column `sub_region_code` on `Household` and `Member`, denormalised
   from the existing `sub_region` FK so the partition key sits on the
   row itself. Indexed.
2. `Household.save()` and `Member.save()` populate the column at write
   time. Member inherits from its household.
3. Backfill data migration (postgres-only RunPython) populates the
   column for any rows that pre-date this migration.
4. A composite index `(sub_region_code, id)` matches the partition-aware
   query shape so the upcoming cut-over is index-free.

### Sprint 2 — what executes the cut-over

The actual `CREATE TABLE ... PARTITION BY LIST (sub_region_code)` plus
partition-attach DDL runs in a blue-green schema migration documented
under `infrastructure/runbooks/migration-reverse-plans/sprint-2/`. The
migration:

1. Renames `data_management_household` → `household_unpartitioned`.
2. Creates the new partitioned `data_management_household` with the same
   schema.
3. Creates the 9 partitions plus a `_unassigned` DEFAULT partition.
4. Replays `INSERT INTO data_management_household SELECT * FROM
   household_unpartitioned` inside a transaction.
5. Drops `household_unpartitioned` once verified.
6. Repeats for `data_management_member`.

This is a real cut-over; running it requires:
- A maintenance window or blue-green deploy (the registry can serve
  reads from the unpartitioned table while the partitioned table
  builds).
- Confirmation from US-S2-007 (the partition cut-over ticket) that no
  bulk load is mid-flight.
- ADR-0003 reverse plan recorded against the release.

## Consequences

### Positive

- **Partition key is already on every row** as of Sprint 1 — the
  cut-over migration becomes a schema rewrite, not a data migration.
- **`sub_region_code` is queryable today** as a denormalised cache,
  which speeds up Parish Chief admin filters even before partitioning.
- **Index pattern aligns** — `(sub_region_code, id)` is the post-
  partition query path.

### Negative / costs

- Denormalisation drift: if a household's `sub_region` FK changes
  without `sub_region_code` being repopulated, the row would land in
  the wrong partition post-cut-over. Mitigated by `save()` overrides
  and a CI invariant test.
- Member rows duplicate their household's `sub_region_code` — extra
  ~14 bytes per row. At 50M members that's ~700 MB; acceptable for the
  query-locality gain.

### Risks accepted

- The Sprint 2 cut-over still requires careful execution. If any bulk
  load is in-flight during the window, we have to coordinate. The
  runbook calls this out.

## Alternatives considered

- **Composite PK `(sub_region_code, id)`.** Rejected. Django FKs into
  the table would have to use the composite, which Django ORM cannot
  express cleanly and which would force `Member.household` to carry
  both columns. The denormalised approach keeps the ORM untouched and
  lets Postgres-side partition pruning still work.
- **Range partitioning by `created_at`.** Rejected. Cold-storage
  archival is appealing but our hot-read pattern is geography, not
  recency. Range partitioning would not help Parish Chief queries.
- **`django-postgres-extra`.** Considered. Useful library but
  introducing it for one table pair is overkill, and the raw-SQL
  RunPython migration is straightforward enough.

## Compliance

- SAD §5.5 (indexing and partitioning).
- ADR-0003 (reverse plan attached to the Sprint 2 release).
- DPPA 2019 §27 (data accuracy) — denormalised key requires the
  invariant test described above.

## Re-open triggers

1. Sub-region taxonomy changes (UBOS administrative review). The
   partition list and the DEFAULT partition can absorb new sub-regions;
   removed ones become empty partitions until the next maintenance.
2. Read pattern shifts away from sub-region locality (e.g., national
   roll-ups dominate). Range or hash partitioning would be revisited.

---

End of ADR-0005.
