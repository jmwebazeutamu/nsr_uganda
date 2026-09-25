"""PMT Celery tasks.

`recompute_band_thresholds_task` (US-S22-PMT-BAND-THRESHOLD) walks
every ACTIVE PMTModelVersion's PMTResult set once, computes the
empirical score at each percentile rank declared on
`band_cutoffs`, and appends one fresh PMTBandThreshold row per
band per model version. Daily 02:00 EAT in production beat
schedule (see nsr_mis/celery.py); also importable so the seed
migration + tests can call the underlying function directly.

Append-only: every run writes new rows. Stale rows survive for
audit + calibration-drift trend analysis. `apps.pmt.engine.derive_band`
reads the LATEST row per (model_version, band_name).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction

from apps.pmt.models import PMTBandThreshold, PMTModelVersion, PMTResult
from apps.security.audit import emit as emit_audit
from celery import shared_task

log = logging.getLogger(__name__)


def recompute_band_thresholds(actor: str = "celery-beat") -> dict:
    """Recompute empirical band thresholds for every ACTIVE PMT model.

    Walks every PMTModelVersion with status="active". For each:
      1. Streams every PMTResult.score for that model whose Household
         is not soft-deleted into an in-memory float list.
      2. Reads `band_cutoffs` from the model. Each entry is a
         (band_name, percentile_rank) pair — the rank is the bottom-N
         percentile that defines the band's upper boundary.
      3. Computes `statistics.quantiles(...)`-style percentile values
         using linear interpolation between sorted scores. Stdlib
         only — keeps numpy out of the dependency surface.
      4. Appends one PMTBandThreshold row per band, emits one
         AuditEvent per write.

    Returns a summary dict ({model_id: {band: threshold}}) so the
    scheduled wrapper can log volume and the seed-migration call
    site can assert on what was written.
    """
    summary: dict[str, dict[str, float]] = {}
    actives = list(
        PMTModelVersion.objects
        .filter(status="active")
        .order_by("version"),
    )
    if not actives:
        log.info("recompute_band_thresholds: no ACTIVE model versions")
        return summary

    for mv in actives:
        summary[str(mv.id)] = _recompute_for_model(mv, actor=actor)
    return summary


@transaction.atomic
def _recompute_for_model(
    mv: PMTModelVersion, *, actor: str,
) -> dict[str, float]:
    """Inner per-model worker. Atomic so a partial recompute either
    lands every band row or none of them — `derive_band` would
    otherwise see a torn state where some bands moved and others
    stayed."""
    band_cutoffs = mv.band_cutoffs or {}
    if not band_cutoffs:
        log.warning(
            "recompute_band_thresholds: PMTModelVersion v%s has empty "
            "band_cutoffs; nothing to recompute", mv.version,
        )
        return {}

    # PMTResult.score is Decimal; coerce to float once for the
    # percentile math. household__is_deleted=False so soft-deleted
    # rows don't skew the population estimate.
    scores: list[float] = list(
        PMTResult.objects
        .filter(model_version=mv, household__is_deleted=False)
        .values_list("score", flat=True)
        .iterator(chunk_size=10000),
    )
    scores_f = [float(s) for s in scores]
    if not scores_f:
        # Bootstrap. No stored results does not mean no population.
        #
        # Thresholds are computed from scores; scores are written by
        # `recompute_for_household`; and that cannot band a household
        # until thresholds exist. A registry starting from empty was
        # therefore stuck: every promotion went through unscored, and
        # this job kept finding nothing to compute from.
        #
        # So score the promoted households here instead of waiting for
        # rows that will never arrive. `compute_score` deliberately
        # does not band — asking for a band is what the deadlock was.
        scores_f = _bootstrap_scores(mv)

    sample_size = len(scores_f)
    if sample_size == 0:
        log.warning(
            "recompute_band_thresholds: PMTModelVersion v%s has no scores "
            "and no households to score; nothing to compute. derive_band "
            "will raise until this has something to work from.",
            mv.version,
        )
        emit_audit(
            "recompute_skipped", "pmt_model_version", str(mv.id),
            actor=actor, actor_kind="system",
            reason=f"no PMTResults and no scorable households for v{mv.version}",
        )
        return {}

    sorted_scores = sorted(scores_f)
    written: dict[str, float] = {}
    for band_name, rank in band_cutoffs.items():
        try:
            rank_int = int(rank)
        except (TypeError, ValueError):
            log.warning(
                "recompute_band_thresholds: band %s on v%s has "
                "non-integer rank %r; skipping band",
                band_name, mv.version, rank,
            )
            continue
        threshold = _percentile(sorted_scores, rank_int)
        row = PMTBandThreshold.objects.create(
            model_version=mv,
            band_name=band_name,
            score_threshold=Decimal(str(round(threshold, 6))),
            percentile_rank=rank_int,
            sample_size=sample_size,
            computed_by=actor,
        )
        written[band_name] = threshold
        emit_audit(
            "compute", "pmt_band_threshold", str(row.id),
            actor=actor, actor_kind="system",
            reason=(
                f"v{mv.version} {band_name} p{rank_int} "
                f"= {threshold:.6f} (n={sample_size})"
            ),
            field_changes={
                "model_version_id": str(mv.id),
                "band_name": band_name,
                "score_threshold": threshold,
                "percentile_rank": rank_int,
                "sample_size": sample_size,
            },
        )
    return written



def _bootstrap_scores(mv: PMTModelVersion) -> list[float]:
    """Score the promoted population directly, for the first run.

    Only reached when the model has no stored `PMTResult` rows at all.
    That is the cold-start state: households have been promoted (they
    are not blocked on PMT — see `services.recompute_for_household`)
    but none could be banded, so none was stored.

    Scores only. Banding is what this job is computing the inputs for,
    and `compute_score` is separable from `compute_pmt` precisely so
    this path cannot ask for the answer it is trying to produce.

    A household the model cannot score at all is skipped rather than
    failing the run: one malformed record must not keep the whole
    registry unbanded.
    """
    from apps.data_management.models import Household

    from .engine import compute_score

    scores: list[float] = []
    skipped = 0
    households = (
        Household.objects
        .filter(is_deleted=False)
        .select_related(
            "dwelling", "utilities", "livelihood",
            "food_security", "food_consumption",
            "head_member",
            "head_member__education", "head_member__employment",
        )
        .prefetch_related(
            "members", "assets", "livestock", "crops",
            "shocks", "coping_strategies",
        )
        .iterator(chunk_size=500)
    )
    for household in households:
        try:
            score, _snapshot = compute_score(household, mv)
        except Exception:  # noqa: BLE001 — one bad row must not stop the sweep
            skipped += 1
            continue
        scores.append(float(score))

    log.info(
        "recompute_band_thresholds: bootstrapped %s score(s) for v%s "
        "directly from households (%s skipped); no stored PMTResults yet",
        len(scores), mv.version, skipped,
    )
    return scores


def _percentile(sorted_scores: list[float], rank: int) -> float:
    """Linear-interpolated percentile, stdlib-only.

    Mirrors the behaviour of `numpy.percentile(..., interpolation=
    "linear")` for ints 0–100. Out-of-range ranks clamp to the
    endpoints (rank<=0 → minimum, rank>=100 → maximum). Length-1
    samples return their single value for any rank.
    """
    if not sorted_scores:
        raise ValueError("_percentile() requires at least one score")
    n = len(sorted_scores)
    if rank <= 0 or n == 1:
        return sorted_scores[0]
    if rank >= 100:
        return sorted_scores[-1]
    # Position in the sorted array — 0-indexed, real-valued so the
    # interpolation between two neighbouring values is exact.
    pos = (rank / 100.0) * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    fraction = pos - lo
    return sorted_scores[lo] + (sorted_scores[hi] - sorted_scores[lo]) * fraction


@shared_task(name="apps.pmt.tasks.recompute_band_thresholds_task")
def recompute_band_thresholds_task() -> dict:
    """Beat-driven wrapper. Daily 02:00 EAT in production.

    Off-peak hour matches the existing audit-chain verify slot — the
    full-population percentile pass on 12M+ scores is the
    second-largest registry sweep we run (the audit verify is
    larger). Both can co-exist because percentile reads the
    PMTResult set, not AuditEvents.
    """
    summary = recompute_band_thresholds(actor="celery-beat")
    log.info(
        "recompute_band_thresholds: %d active model version(s) processed",
        len(summary),
    )
    return summary
