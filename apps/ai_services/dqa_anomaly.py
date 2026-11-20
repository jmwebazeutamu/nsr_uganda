"""DQA anomaly flags (feature `dqa.anomaly`, ADR-0045).

Scores households with a registered robust-z model over fields the DQA payload
producer emits. Writes only `AiSuggestion`. It creates no `DqaResult`, no
`DqaEvaluation` and no `dqa.household.flag` audit event: an AI flag is not a
DQA rule outcome and must not be able to block or route a household.

Gate: there is no recorded reviewer disposition of an AI flag yet, so
`evaluate_feature` cannot measure this feature and it stays in SHADOW.
"""

from __future__ import annotations

from apps.dqa.pipeline import household_to_dqa_payload

from .models import FeatureCode
from .services import load_scorer, record_run

SUBJECT_TYPE = "household"


def score_households(households, *, actor: str = "system", watermark=None):
    """`households`: an iterable of Household with `members` prefetched."""
    scorer, model = load_scorer(FeatureCode.DQA_ANOMALY)
    items, skipped = [], 0
    for h in households:
        result = scorer.score(household_to_dqa_payload(h))
        if result is None:
            skipped += 1
            continue
        score, zs = result
        items.append({
            "subject_id": str(h.id), "score": score,
            "details": {"flagged": score >= scorer.threshold, "z": zs,
                        "threshold": scorer.threshold},
        })
    return record_run(
        FeatureCode.DQA_ANOMALY, model, items, subject_type=SUBJECT_TYPE, actor=actor,
        skipped=skipped, note="households with no computable feature are skipped",
        watermark=watermark,
    )


def score_recent_households(*, limit: int, actor: str = "system"):
    """Score households changed since the last run covered. Returns the AiRun,
    or None when there is nothing new (no run row, no audit event).

    The watermark is the newest `updated_at` the run covered. When the batch
    is cut off by `limit` it is stepped back one microsecond so households
    sharing the last timestamp are picked up next time rather than skipped;
    the cost is that boundary household is scored twice, and evaluation reads
    only the latest suggestion per subject.
    """
    from datetime import timedelta

    from apps.data_management.models import Household

    from .models import AiRun

    # Fails closed before any query when the feature is off.
    load_scorer(FeatureCode.DQA_ANOMALY)
    last = (
        AiRun.objects.filter(feature=FeatureCode.DQA_ANOMALY, watermark__isnull=False)
        .order_by("-watermark").first()
    )
    qs = Household.objects.filter(is_deleted=False)
    if last:
        qs = qs.filter(updated_at__gt=last.watermark)
    batch = list(qs.order_by("updated_at", "id").prefetch_related("members")[:limit])
    if not batch:
        return None
    newest = batch[-1].updated_at
    watermark = newest - timedelta(microseconds=1) if len(batch) == limit else newest
    return score_households(batch, actor=actor, watermark=watermark)
