# DAT-DDUP — Deduplication

!!! info "Status"
    **Built and in use** — tier 1 (NIN deterministic), tier 2 (phone), side-by-side compare, merge-commit, match-model versioning. Tier 3 (probabilistic) **Planned** for S5.

DDUP finds and resolves duplicate households or members. Shared service callable from both DIH (during ingest) and the registry (on demand).

## What it does

Runs candidate matchers across the staged record and the canonical store. Flags candidates above the confidence threshold. Surfaces the dedup dashboard and the side-by-side compare. Commits merges in a single transaction (atomic across Household, Member, Relationships, detail entities, and version chains).

## Where it lives

| Path | What |
|---|---|
| `apps/ddup/` | Django app |
| `/api/v1/ddup/` | DRF surface |
| `/design/v0.1/screens/screens-dedup.jsx` | Dedup workbench |
| `/design/v0.1/screens/screens-admin-workflow-ddup.jsx` | Match-model editor |

## Endpoints

| Endpoint | Verb | Purpose |
|---|---|---|
| `/api/v1/ddup/candidates/` | GET | Pending candidates, ABAC-scoped |
| `/api/v1/ddup/candidates/{id}/` | GET | One candidate pair with compare data |
| `/api/v1/ddup/match-pairs/{id}/merge/` | POST | Commit a merge (transactional) |
| `/api/v1/ddup/match-pairs/{id}/discard/` | POST | Keep one record intact, soft-delete the other |
| `/api/v1/ddup/match-pairs/{id}/reject/` | POST | Mark the pair as not-a-duplicate; both stay registered |
| `/api/v1/ddup/merge-decisions/{id}/reverse/` | POST | Un-merge within the 30-day window |
| `/api/v1/ddup/match-models/` | GET, POST | The matcher catalogue |
| `/api/v1/ddup/match-models/{id}/approve/` | POST | Dual-approve a new matcher |

## Three compare-screen actions

The compare screen offers three terminal actions on a pending pair. They differ in what happens to the field values and which record survives:

| Action | Both records are… | What happens to the survivor | What happens to the loser |
|---|---|---|---|
| **Reject pair** | NOT duplicates | Stays registered, unchanged | Stays registered, unchanged. Pair marked REJECTED so it won't re-queue. |
| **Discard duplicate** (v0.3) | The same person, but the loser is bad data | Untouched | Soft-deleted with `merged_into=survivor`; `Household.head_member` references re-point |
| **Merge** | The same person, both have valid partial information | Fields updated per the operator's per-field A/B picks | Soft-deleted exactly as Discard |

Discard and Merge both write the loser the same way on disk — the difference is whether any field values move. **Both are reversible** through the same 30-day window via `reverse_merge_decision`. The pair flips to `MERGED` in either case; the `MergeDecision.action` records the distinction (`merge` vs `discard_loser`) so audit + reporting can tell them apart.

## Key entities

- `MatchCandidate` — one row per pair.
- `MatchModel` — versioned, dual-approved.
- `MergeDecision` — the audit-bearing record of an operator merge.

## Matcher tiers

| Tier | Matcher | Confidence | Status |
|---|---|---|---|
| 1 | NIN hash equality | 1.0 | Built |
| 2 | Normalised phone equality | 0.95 | Built |
| 3 | Composite name + DOB + parish | 0.80 – 0.95 | Planned (S5) |

## ADRs

- [ADR-0017](../appendices/adrs.md) — Detail entities reparent on merge

## Stories

US-082, US-083, US-084, US-085, US-086, US-087.
