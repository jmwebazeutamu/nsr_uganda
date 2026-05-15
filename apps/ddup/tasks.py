"""Celery tasks for DDUP.

auto_merge_high_confidence_pairs_task — recurring sweep scheduled
by Celery beat (see nsr_mis/celery.py). Wraps the same service the
management command would call (no command for this one yet; the
sweep is automatic by design and shouldn't need ops to fire it).
"""

from __future__ import annotations

from celery import shared_task

from .services import auto_merge_high_confidence_pairs


@shared_task(name="apps.ddup.tasks.auto_merge_high_confidence_pairs_task")
def auto_merge_high_confidence_pairs_task() -> dict[str, int]:
    """Counts dict surfaces on the Celery result backend for ops
    metrics — rising 'skipped' values indicate reviewer races."""
    return auto_merge_high_confidence_pairs()
