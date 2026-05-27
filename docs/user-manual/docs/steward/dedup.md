# Dedup workbench

!!! info "Status"
    **Built and in use** — tier-1 NIN deterministic matcher, dedup dashboard, side-by-side compare, and merge-commit transaction are live (US-082, US-083, US-084, US-087). Tier-2 phone matcher landed in S2. Tier-3 probabilistic matching is **Planned** for S5.

The dedup workbench is where two records that might be the same person get resolved into one. The system never auto-merges sensitive records; you decide.

## How candidates arrive

| Tier | Trigger | Confidence | Default behaviour |
|---|---|---|---|
| Tier 1 — NIN deterministic | NIN hash equal | 1.0 | Auto-flag, route to your queue |
| Tier 2 — Phone deterministic | Normalised phone equal | 0.95 | Auto-flag, route to your queue |
| Tier 3 — Probabilistic (Planned) | Composite name + DOB + parish score | 0.80 to 0.95 | Auto-flag with reason breakdown |

## Where to find it

| Surface | Path |
|---|---|
| Console screen | `/console/` → "Dedup" |
| Source JSX | `/design/v0.1/screens/screens-dedup.jsx → DedupScreen` |
| API list | `/api/v1/ddup/candidates/` |
| API merge | `/api/v1/ddup/merge/` |
| Audit action | `ddup_merge_committed` |

## The compare screen

Three columns (or four for a three-way match):

| Column | Source |
|---|---|
| Candidate A | One of the matched households |
| Candidate B | The other matched household |
| Merge Result | Your chosen merged record |
| (Candidate C) | Optional third candidate for three-way matches |

For every field:

- **A** radio takes A's value.
- **B** radio takes B's value.
- **Both** radio concatenates (list fields only; non-list fields disable Both with a tooltip).
- Hovering shows the per-field similarity score.

The header chip shows why the matcher flagged the pair (e.g. "NIN deterministic match").

## Committing a merge

The **Commit** button stays disabled until:

- Every field has a chosen value.
- The reason note is non-empty.

On commit, in a single transaction:

1. The merged record is written to the surviving Household ID.
2. The losing Household is set to `voided` with a pointer to the survivor.
3. All Members, Relationships, and detail rows reparent to the survivor.
4. A new HouseholdVersion row records the merge.
5. PMT recompute is queued for the survivor.
6. One AuditEvent with action `ddup_merge_committed` is written, including `surviving_id`, `loser_id`, and your reason.
7. A toast shows the surviving and loser IDs.

If anything in the transaction fails, the entire merge rolls back. No partial state.

## Three terminal actions (v0.3)

The compare screen offers three buttons above the field-pick grid:

- **Reject pair** — the two records ARE NOT the same person. Both stay registered. Use this when a tier-1 NIN match turned out to be a NIN-typo collision or a tier-2 phone match resolves to two siblings who share a phone.
- **Discard duplicate** (NEW) — the two records ARE the same person, but the loser is bad data (test entry, double-tap submission, garbled re-capture). The survivor stays untouched — no field combining. The loser is soft-deleted exactly like a merge loser; the 30-day reverse window applies.
- **Commit merge** — the two records ARE the same person and both have valid partial information. Combine the fields per your A / B picks (see grid).

Discard is a focused modal: radio buttons to pick which record to keep + a reason textarea (≥ 6 chars). No field-by-field grid — that's the whole point. The pair lands in MERGED state with `MergeDecision.action = "discard_loser"` so reporting can tell discard apart from merge.

## When NOT to merge or discard

- The candidates have different NINs and only a name + DOB match. Send to tier-3 probabilistic review (Planned) or escalate.
- One candidate is recent and the other has been registered for years with referrals in flight. Open a ticket for the Programme Owner first.
- The records are clearly two different people who share a name. **Reject pair** with a reason; the matcher records this as a feedback signal.

## Match model versioning

The matcher itself follows the same dual-approval lifecycle as DQA rules.

| Field | Meaning |
|---|---|
| `model_id` | Stable code (e.g. `MM-NIN`, `MM-PHONE`) |
| `version` | Auto-incremented |
| `weights` | JSON for tier-3 weights (Planned) |
| `status` | `draft` → `pending_approval` → `active` → `superseded` |

Change a model only via the dual-approval flow. The Admin Console DDUP workflow screen surfaces this at `/admin-console/workflow/ddup/`.

## Related

- [DIH review queue](dih-review-queue.md)
- [DAT-DDUP module reference](../modules/dat-ddup.md)
- ADR-0017 — Detail entities as tables (Members and detail rows reparent on merge)
- US-083 acceptance criteria — see `/design/v0.1/acceptance.md` §5
