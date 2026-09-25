# DAT-DDUP — Deduplication

!!! info "Status"
    **Built and in use** — tier 1 (NIN deterministic) is the only tier enabled in production. Tier 2 (phone) and tier 3 (probabilistic) are declared in the active model but **switched off**. Side-by-side compare, merge-commit and model versioning are live. Revised 25 September 2026.

DDUP finds and resolves duplicate households or members. Shared service callable from both DIH (during ingest) and the registry (on demand).

## The active model decides everything

Matching policy lives in `DdupModelVersion.config`, not in code. The
approved model declares, for every tier it enables, the fields, the
method, the weights and the thresholds.

**There are no defaults.** A model that does not declare them is
unusable rather than silently matching people by some other rule — see
`apps/ddup/config.py`.

Production today:

| Version | Status | Tiers declared | Tiers enabled |
|---|---|---|---|
| v1 | retired | — | — |
| v2 | active | tier1, tier2, tier3 | **tier1 only** |

!!! danger "What happens when the contract and the data disagree"
    On 22 September 2026 the configuration contract was deployed while
    the active model (v1) did not satisfy it. Every call to
    `get_active_model_version()` raised, which took out DIH promotion
    and the nightly discovery run for about a day.

    v2 was authored and activated to resolve it. The lesson is in
    `docs/PROD_SETUP_LOG.md`: **deploying a range is deploying all of
    it** — check that the configuration a new contract needs is
    actually in the database before the image goes out.

!!! note "Turning a tier on is a configuration change, not a release"
    Enabling tier 2 or tier 3 means approving a new model version. It
    does not need a deploy, and it should not be done without the
    weights and thresholds that go with it. Tier 3 re-enablement is
    tracked as **US-150**.

## Auto-merge is off

`auto_merge_high_confidence_pairs` soft-deletes a Member with nobody in
the loop, so it runs only when the approved model version says
`auto_merge_enabled`. It does not today.

That switch lives in the model version rather than in settings,
deliberately: turning it on goes through the same dual approval as the
weights and the threshold.

## Discovery runs nightly

The three `discover_*` services had nothing calling them — not the DIH
pipeline, not beat, not an endpoint — so tiers 2 and 3 had never
produced a pair, and the hourly auto-merge sweep had been a no-op since
the day it was scheduled. Discovery is now on Celery beat at 04:00,
after every job that writes members, and runs incrementally from the
last run's watermark rather than re-sweeping everything.

Resolved pairs stay resolved: a rejected pair is not re-created as
pending on the next run.

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
| `/api/v1/ddup/match-pairs/` | GET | Pending candidates, ABAC-scoped |
| `/api/v1/ddup/match-pairs/{id}/` | GET | One candidate pair with compare data |
| `/api/v1/ddup/match-pairs/{id}/merge/` | POST | Commit a merge (transactional) |
| `/api/v1/ddup/match-pairs/{id}/discard/` | POST | Keep one record intact, soft-delete the other |
| `/api/v1/ddup/match-pairs/{id}/reject/` | POST | Mark the pair as not-a-duplicate; both stay registered |
| `/api/v1/ddup/merge-decisions/{id}/reverse/` | POST | Un-merge within the 30-day window |
| `/api/v1/ddup/model-versions/` | GET, POST | The matcher catalogue |
| `/api/v1/ddup/model-versions/{id}/` | POST | Dual-approve a new matcher |

## Three compare-screen actions

The compare screen offers three terminal actions on a pending pair. They differ in what happens to the field values and which record survives:

| Action | Both records are… | What happens to the survivor | What happens to the loser |
|---|---|---|---|
| **Reject pair** | NOT duplicates | Stays registered, unchanged | Stays registered, unchanged. Pair marked REJECTED so it won't re-queue. |
| **Discard duplicate** (v0.3) | The same person, but the loser is bad data | Untouched | Soft-deleted with `merged_into=survivor`; `Household.head_member` references re-point |
| **Merge** | The same person, both have valid partial information | Fields updated per the operator's per-field A/B picks | Soft-deleted exactly as Discard |

Discard and Merge both write the loser the same way on disk — the difference is whether any field values move. **Both are reversible** through the same 30-day window via `reverse_merge_decision`. The pair flips to `MERGED` in either case; the `MergeDecision.action` records the distinction (`merge` vs `discard_loser`) so audit + reporting can tell them apart.

## Key entities

- `MatchPair` — one row per pair.
- `DdupModelVersion` — versioned, dual-approved.
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
