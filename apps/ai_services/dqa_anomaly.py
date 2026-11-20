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


def score_households(households, *, actor: str = "system"):
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
    )
