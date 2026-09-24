# US-150 — A governed tier-3 probabilistic matching model

**Status:** Backlog (already in `docs/03_backlog.xlsx`); raised to
**Must** on 25 September 2026
**Epic:** 15. Deduplication & Record Matching
**Module:** DAT-DDUP
**Actor:** System Administrator / DQA Approver / DPO

This file records what the 25 September production incident added to a
story that already existed. The story itself is unchanged in intent —
"features, comparators, weights, blocking field, review threshold and
any auto-merge policy come solely from the approved DDUP configuration".
What changed is that it now has a live trigger.

## Tier 3 is off in production

`DdupModelVersion v2` was activated on 25 September to end an outage.
The approved-model contract in `apps/ddup/config.py` shipped while the
active model still carried the pre-contract shape, so
`get_active_model_version()` raised and took DIH promotion and the
nightly discovery run with it. v2 restates tier 1 — NIN exact match —
in the required shape and stops there.

It stops there deliberately. Tier 3 had been running on this, in
`services.py`:

```python
weights = cfg.get("weights") or {
    "surname": 0.30, "first_name": 0.30,
    "date_of_birth": 0.15, "sex": 0.10, "village": 0.15,
}
threshold = cfg.get("threshold", 0.85)
```

The active model version carried no `tier3` section at all, so those
code defaults *were* the matching policy — changeable by any release,
never through dual approval. Carrying them into an approved model to
restore service would have turned a developer's default into policy by
the back door, which is the thing this story exists to prevent.

## What is true while it stays off

- No new probabilistic pairs are discovered. Tier 1 (NIN) and tier 2
  (phone) are unaffected — tier 2 does not gate on the config.
- The **17 pending tier-3 pairs already queued are untouched** and
  still reviewable. Nothing was withdrawn.
- Duplicates sharing neither a NIN nor a phone number go unnoticed,
  which is the case tier 3 exists for. The longer it is off, the larger
  the backlog when it returns.

## Blockers: what cleared, what has not

**Cleared.** The DDUP configuration contract (`apps/ddup/config.py`)
validates a model against the field dictionary and the declared
derived-field registry, and refuses an incomplete one. The comparator
registry exists (`_tier3_comparators`), both scorers read the approved
model through it, and per-field scores are recorded under the canonical
field references the dictionary uses.

`manage.py propose_tier3_weights` authors a DRAFT and stops; `--show`
writes nothing. It proposes:

```
surname        0.30 -> 0.35    date_of_birth  0.15 -> 0.20
first_name     0.30 -> 0.35    sex            0.10 -> 0.10
village        0.15 ->  —      removed: tier 3 blocks BY village, so the
                               feature scored 1.0 for every pair the
                               model ever compared
```

0.30 of the weight was free to anyone sharing a village and a birth
year. The scorer was fixed the same week — `birth_date_proximity`
replaced `year_proximity`, taking the false Akello/Okello match from
0.967 to 0.877, below the auto-merge line.

**Not cleared.** The calibration dataset, the governance policy, and
DPO approval.

## Added to the acceptance criteria

The criteria already in the backlog stand. These come from the
incident:

- The weights and thresholds are **decided**, not inherited. Whoever
  approves states why each number is what it is; the
  `propose_tier3_weights` output is the starting point, not the answer.
- `auto_merge_enabled` is a separate, explicit decision from enabling
  tier 3. Auto-merge soft-deletes a Member with nobody in the loop; the
  default stays off.
- Calibration is reported **before** activation: how many of the 17
  pending pairs the new model would have created, and how many it would
  have auto-merged had the flag been on.
- The Akello / Okello pair — two different people — scores below the
  review threshold under the approved model, and a test pins it.
- After activation, a discovery run is executed and its
  `tier3_created` / `comparisons` counts recorded in
  `docs/PROD_SETUP_LOG.md`.

## Note

Do not implement a default. A weight chosen by a developer to make the
tests pass is what this story exists to undo — the same reason US-130
refuses to pick a retention period.
