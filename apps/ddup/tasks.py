"""Celery tasks for DDUP.

auto_merge_high_confidence_pairs_task — recurring sweep scheduled
by Celery beat (see nsr_mis/celery.py). Wraps the same service the
management command would call (no command for this one yet; the
sweep is automatic by design and shouldn't need ops to fire it).
It is disabled unless the active DdupModelVersion turns it on.

discover_pairs_task — nightly discovery across all three tiers. Until
this existed nothing called the discover_* services at all, so tier 2
and tier 3 had never produced a pair and the auto-merge sweep above
had nothing to sweep.
"""

from __future__ import annotations

from celery import shared_task

from .services import auto_merge_high_confidence_pairs


@shared_task(name="apps.ddup.tasks.auto_merge_high_confidence_pairs_task")
def auto_merge_high_confidence_pairs_task() -> dict[str, int]:
    """Counts dict surfaces on the Celery result backend for ops
    metrics — rising 'skipped' values indicate reviewer races."""
    return auto_merge_high_confidence_pairs()


@shared_task(name="apps.ddup.tasks.discover_pairs_task")
def discover_pairs_task(full: bool = False) -> dict:
    """Nightly duplicate discovery.

    Incremental: tier 3 only revisits village blocks holding a member
    touched since the last successful run. `full=True` forces a complete
    sweep and should be fired deliberately, not scheduled — at the
    12M-household target a full tier-3 pass is ~2x10^10 comparisons.
    """
    from .services import run_discovery

    run = run_discovery(full=full, actor="ddup-nightly")
    return {
        "run_id": run.id,
        "scanned_from": run.scanned_from.isoformat() if run.scanned_from else None,
        "members_considered": run.members_considered,
        "tier1": run.tier1_created,
        "tier2": run.tier2_created,
        "tier3": run.tier3_created,
        "comparisons": run.comparisons,
        "status": run.status,
    }
