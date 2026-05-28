# ADR-0023 Appendix A — Cell-reconstruction risk-probe specification

- **Companion to**: [ADR-0023 — Data Explorer module](0023-data-explorer.md)
- **Status**: Proposed
- **Date**: 27 May 2026

This file specifies the re-identification risk-probe test that gates every DATA-EXP release. It is referenced from §"Risk register" and §"Implementation notes" of the parent ADR.

## Probe goal

Assert that **no individual household and no individual member can be reconstructed from any combination of 100 sequential aggregate queries with up to 3 overlapping filter dimensions.** The probe is a CI-gated test that runs against the staging matview snapshot (anonymised). A failure blocks the release.

## Threat model

- Attacker has a valid `EXPLORER` Keycloak realm role.
- Attacker knows the catalogue (it is published metadata; not a secret).
- Attacker can build any aggregate query the suppressor admits.
- Attacker can run up to 100 queries within the daily throttle (raise the cap for the probe; lower it for real users).
- Attacker's objective: identify the count of households / members in a cell whose true count is below `k_floor` for the relevant PrivacyClass, **without** the server returning that count directly.

## Attack pattern

The probe implements a known small-multiples reconstruction attack:

1. **Pick a target cell.** A household-level cell with true count = 1, 2, or 3 (i.e., < `k_floor = 5` for Internal) in `mv_explorer_household_by_subcounty_pmt`. Example: `(sub_county=Tapac, pmt_band=poorest_10pct)` with true count = 2.

2. **Build the base aggregate.** Query `count(Household) GROUP BY sub_county, pmt_band` filtered to `sub_region=Karamoja`. Suppressor returns the target cell as `null + suppressed: true`. Attacker now knows the cell exists but not its count.

3. **Introduce a third dimension.** Add `head_age_band` to the projection. The matview groups by `(sub_county, pmt_band, head_age_band)`. Target cell may split into smaller cells, all suppressed.

4. **Differencing attempt.** Run two queries:
    - `Q1 = count where sub_county=Tapac AND pmt_band=poorest_10pct AND head_age_band IN (15-29, 30-44, 45-59)`
    - `Q2 = count where sub_county=Tapac AND pmt_band=poorest_10pct AND head_age_band IN (15-29, 30-44)`

    If `Q1 - Q2` returns a small number, the attacker has learned the count in the `(45-59)` cell. **The probe asserts that the suppressor returns `null` for both Q1 and Q2 if either has a result below k_floor, so the differencing yields `null - null = no information`.**

5. **Sequential narrowing.** Iterate steps 3–4 across 100 queries that progressively narrow the filter (adding `head_sex`, `dwelling_type`, `chronic_illness_present`, etc.). Each query uses up to 3 overlapping filter dimensions with the previous queries (the "3-overlap" budget from the spec).

6. **Cross-matview attempt.** Mix queries against `mv_explorer_household_by_subcounty_pmt` and `mv_explorer_household_by_subcounty_demographics` for the same target geography. Test that no combination of suppressed cells across matviews reveals the underlying count.

## Configured risk threshold

**No household record and no member record is reconstructible from any combination of 100 sequential queries with up to 3 overlapping filter dimensions across all matviews available to the test actor's PrivacyClass.**

*Reconstructible* is defined as: the probe terminates with a posterior distribution over the cell's true count that assigns ≥ 90% probability to a single integer value. If the posterior remains spread over ≥ 3 integers with no single peak ≥ 90%, the cell is **not reconstructible**.

## Test harness

- Lives in `apps/data_explorer/tests/test_risk_probe.py`.
- Marked `@pytest.mark.slow` and `@pytest.mark.risk_probe`.
- Runs against the staging matview snapshot in CI (anonymised) — never against production.
- Generates a deterministic seed of 100 queries from a YAML scenario file `apps/data_explorer/tests/risk_probe_scenarios.yaml` (so the probe is reproducible and reviewable).
- Asserts `AggregateQueryLog.suppressed_cell_count > 0` for the small-cell scenarios.
- Asserts the differencing computation `Q1.count - Q2.count` always returns `None` (not a small integer) for any pair where either is suppressed.
- Asserts the `detect_overlap_burst` task flags the probe actor by query #50 (early-warning sanity check).

## What the probe does *not* cover

- Side-channel timing attacks. The suppressor returns in O(cells) time regardless of result, but query execution time varies with the matview size. Out of scope for MVP-1.
- Attacks combining DATA-EXP queries with information from outside the registry (e.g., correlating with leaked partner datasets). Out of scope.
- Collusion between two `EXPLORER` actors. The query log is per-actor; cross-actor analytics on the log are a Phase 2 feature.

## Probe outcome handling

- **Probe fails** → release blocked; ADR-0023 update required (either tighten the suppressor or raise k_floor or re-shape the matview to drop the leaky dimension).
- **Probe passes** → release proceeds; the YAML scenario file is updated as new attack patterns are discovered (the threshold is "100 queries" but the scenarios themselves evolve).

End of risk-probe specification.
