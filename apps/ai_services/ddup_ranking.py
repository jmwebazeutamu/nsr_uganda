"""DDUP candidate ranking (feature `ddup.rank`, ADR-0045).

Re-orders PENDING duplicate pairs by a registered model's score. It reads
`MatchPair.per_field_scores` and writes only `AiSuggestion`; it never
touches `MatchPair.status` or creates a `MergeDecision`.

Tier numbering note: in code tier 1 is NIN, tier 2 is phone, tier 3 is
probabilistic. Only pairs that carry `per_field_scores` (tier 3 today) can be
ranked; the rest are counted as skipped, not scored as zero.
"""

from __future__ import annotations

from apps.ddup.models import MatchPair, MergeAction, MergeDecision, PairStatus

from .artifacts import ScoringError
from .models import AiFeature, AiSuggestion, FeatureCode
from .services import (
    Evaluation,
    gate_verdict,
    load_scorer,
    record_run,
)

SUBJECT_TYPE = "match_pair"

# Reviewer decisions that mean "these are the same person" / "they are not".
# on_hold and cross_household say nothing about identity, so they are not labels.
POSITIVE = (MergeAction.MERGE, MergeAction.DISCARD_LOSER)
NEGATIVE = (MergeAction.REJECT,)


def rank_pending_pairs(*, actor: str = "system"):
    """Score every pending pair that carries features. Returns the AiRun.

    Raises AiDisabledError when the feature is off.
    """
    scorer, model = load_scorer(FeatureCode.DDUP_RANK)
    items, skipped = [], 0
    pairs = MatchPair.objects.filter(status=PairStatus.PENDING).only("id", "per_field_scores")
    for pair in pairs.iterator():
        if not pair.per_field_scores:
            skipped += 1
            continue
        try:
            score, contributions = scorer.score(pair.per_field_scores)
        except ScoringError:
            skipped += 1
            continue
        items.append({"subject_id": pair.id, "score": score, "details": {"contributions": contributions}})
    return record_run(
        FeatureCode.DDUP_RANK, model, items, subject_type=SUBJECT_TYPE, actor=actor,
        skipped=skipped, note="pairs without usable per_field_scores are skipped, not scored as zero",
    )


def evaluate() -> Evaluation:
    """Precision of the ranker against what reviewers decided.

    The label is read from MergeDecision by join at call time (ADR-0045 D7).
    Only each pair's latest suggestion counts.
    """
    latest = {}
    for s in AiSuggestion.objects.filter(
        feature=FeatureCode.DDUP_RANK, subject_type=SUBJECT_TYPE,
    ).order_by("created_at"):
        latest[s.subject_id] = s
    decisions = dict(
        MergeDecision.objects.filter(match_pair_id__in=list(latest))
        .values_list("match_pair_id", "action")
    )
    row = AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).first()
    cutoff = ((row.gate_config if row else None) or {}).get("score_cutoff")
    labelled = above = positives = 0
    for pair_id, s in latest.items():
        action = decisions.get(pair_id)
        if action not in POSITIVE + NEGATIVE:
            continue
        labelled += 1
        if cutoff is not None and s.score >= cutoff:
            above += 1
            positives += action in POSITIVE
    return gate_verdict(FeatureCode.DDUP_RANK, labelled, above, positives)


def annotate_rank(qs, *, order_by_rank: bool = False):
    """Attach each pair's newest advisory score to a MatchPair queryset.

    The reviewer-facing surface (ADR-0045 D4): returns `qs` unchanged unless
    the feature is ADVISORY, so shadow suggestions, a switched-off feature and
    a kill switch all read as "no rank". One query for the whole page.

    `order_by_rank` puts the likeliest duplicates first and unranked pairs
    last. It is opt-in so the default queue order is never silently changed.
    """
    from django.db.models import F, OuterRef, Subquery

    from .models import FeatureState
    from .services import feature_state

    if feature_state(FeatureCode.DDUP_RANK) != FeatureState.ADVISORY:
        return qs
    latest = AiSuggestion.objects.filter(
        feature=FeatureCode.DDUP_RANK, subject_type=SUBJECT_TYPE, subject_id=OuterRef("pk"),
    ).order_by("-created_at", "-id")
    qs = qs.annotate(
        ai_score=Subquery(latest.values("score")[:1]),
        ai_model_name=Subquery(latest.values("run__model_version__name")[:1]),
        ai_model_version=Subquery(latest.values("run__model_version__version")[:1]),
    )
    if order_by_rank:
        qs = qs.order_by(F("ai_score").desc(nulls_last=True), "-created_at")
    return qs


def rank_payload(pair) -> dict | None:
    """The `ai_rank` a serializer shows, or None when there is none."""
    score = getattr(pair, "ai_score", None)
    if score is None:
        return None
    return {"score": score, "model": f"{pair.ai_model_name} v{pair.ai_model_version}"}
