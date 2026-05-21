"""Canonical PMT vocabulary anchored to seeded ChoiceLists.

US-PMT-014 / Audit 2026-05-21 §3. The string literals that used to
appear in signals.py / services.py / api.py / tests live here so:

  * downstream code has a single import path, no typos;
  * the ChoiceList migration `0009_seed_pmt_trigger_source` seeds
    exactly these codes — a test in apps.pmt.tests asserts parity.

Add a new trigger source by updating both this module and the
migration in the same commit.
"""

from __future__ import annotations

# Codes for `PMTResult.triggered_by` (also recorded on
# `PMTRun.triggered_by` and the recompute reason audit field).
PMT_TRIGGER_SOURCE_LIST = "pmt_trigger_source"

PMT_TRIGGER_DIH_PROMOTE = "dih_promote"
PMT_TRIGGER_UPD_COMMIT  = "upd_commit"
PMT_TRIGGER_MANUAL      = "manual"
PMT_TRIGGER_BACKFILL    = "backfill"

PMT_TRIGGER_SOURCES: tuple[str, ...] = (
    PMT_TRIGGER_DIH_PROMOTE,
    PMT_TRIGGER_UPD_COMMIT,
    PMT_TRIGGER_MANUAL,
    PMT_TRIGGER_BACKFILL,
)
