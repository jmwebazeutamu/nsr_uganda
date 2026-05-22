"""PMT scoring engine.

Sprint 1 placeholder. The real formula + calibration dataset is open
item O-03; until it lands, the engine evaluates a simple weighted sum
of attribute paths declared on the active PMTModelVersion. The shape
of variables on the model is stable: variables = [
    {"variable": "<dotted.path>", "weight": <float>, "transform": "identity"|"log1p"|"present_as_one"},
    ...
]

Bands derive from band_cutoffs, an inclusive-lower-bound map of
band -> threshold. The default cutoffs treat scores as 0..100.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from .models import Band, PMTBandThreshold, PMTModelVersion

DEFAULT_BAND_CUTOFFS = {
    Band.EXTREME_POVERTY: 0,
    Band.POVERTY: 30,
    Band.VULNERABLE: 60,
    Band.NOT_POOR: 80,
}


def _get(record: Any, path: str) -> Any:
    cur = record
    for part in path.split("."):
        if cur is None:
            return None
        cur = (cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None))
    return cur


def _coerce(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _transform(value: Any, name: str) -> float:
    raw = _coerce(value)
    if name == "log1p":
        return math.log1p(max(raw, 0.0))
    if name == "present_as_one":
        return 1.0 if value not in (None, "", 0, False) else 0.0
    return raw  # identity


def derive_band_from_cutoffs(score: float, cutoffs: dict[str, float]) -> str:
    """Classic fixed-cutoff classifier.

    Returns the band whose lower cutoff is the largest one not
    exceeding `score`. Inclusive lower bound — a score exactly equal
    to a cutoff lands on the higher-band side (this matched the pre-
    US-S22-PMT-BAND-THRESHOLD semantics; the empirical-percentile
    classifier below flips that).
    """
    items = sorted((c, b) for b, c in cutoffs.items())
    band = items[0][1]
    for cutoff, b in items:
        if score >= cutoff:
            band = b
    return band


def derive_band_from_thresholds(score: float, model_version: PMTModelVersion) -> str | None:
    """Percentile-based classifier (US-S22-PMT-BAND-THRESHOLD).

    Reads the most-recent PMTBandThreshold row per band for the given
    model version and returns the band whose score_threshold is the
    largest one not exceeding `score`. Inclusive lower bound — a
    score exactly at the 30th-percentile threshold lands in the
    poorer band (expands eligibility marginally; MGLSD default).

    Returns None when no PMTBandThreshold rows exist for the model
    version — caller falls back to the fixed-cutoff path.
    """
    rows = list(
        PMTBandThreshold.objects
        .filter(model_version=model_version)
        .order_by("band_name", "-computed_at")
    )
    if not rows:
        return None
    # `.distinct("band_name")` is Postgres-only; do it in Python so
    # the sqlite test path produces the same result as production.
    latest_per_band: dict[str, PMTBandThreshold] = {}
    for row in rows:
        latest_per_band.setdefault(row.band_name, row)
    # Walk ascending by threshold; the band whose score_threshold is
    # the LARGEST value not exceeding `score` wins (mirrors the
    # legacy derive_band_from_cutoffs semantic — inclusive lower
    # bound = poorer side wins on the boundary). Scores below the
    # smallest threshold default to that smallest band.
    by_threshold = sorted(
        latest_per_band.values(), key=lambda r: float(r.score_threshold),
    )
    band = by_threshold[0].band_name
    for row in by_threshold:
        if float(row.score_threshold) <= score:
            band = row.band_name
    return band


def derive_band(score: float, target) -> str:
    """Classify a score into a band.

    `target` may be either:
    - a PMTModelVersion instance — the new behaviour. Uses the
      latest empirical PMTBandThreshold rows; falls back to
      `target.band_cutoffs` (fixed-cutoff path) if no threshold rows
      exist yet (e.g. first day after a fresh model activates,
      before the daily beat job has run). Final fallback if both
      are missing is the project default.
    - a dict of band -> cutoff — legacy callers (tests, ad-hoc
      scoring) keep working without modification.

    Two-path fallback is policy-conservative: a fresh system without
    threshold rows still classifies via the existing cutoff dict
    rather than tagging every household as `not_poor` (which the
    ticket suggested but which would erase eligibility on day-zero
    and trip every downstream eligibility check).
    """
    if isinstance(target, PMTModelVersion):
        band = derive_band_from_thresholds(score, target)
        if band is not None:
            return band
        cutoffs = target.band_cutoffs or {
            b.value: float(c) for b, c in DEFAULT_BAND_CUTOFFS.items()
        }
        return derive_band_from_cutoffs(
            score, {str(k): float(v) for k, v in cutoffs.items()},
        )
    return derive_band_from_cutoffs(score, target)


def _safe_attr(parent, attr):
    """Return getattr(parent, attr) but treat Django's RelatedObjectDoesNotExist
    (raised when a reverse OneToOne accessor has no row) as None. Detail
    entities are optional per household; a missing one shouldn't kill scoring.
    """
    try:
        return getattr(parent, attr, None)
    except Exception:  # ObjectDoesNotExist + related variants
        return None


def _household_features(household) -> dict:
    """Build the flat dict the PMT engine walks (US-S22-DE-06).

    Models referenced via dotted path:
      household.<col>                     — Household typed columns
      household.dwelling.<col>            — Dwelling row (one-to-one)
      household.utilities.<col>           — Utilities (one-to-one)
      household.livelihood.<col>          — Livelihood (one-to-one)
      household.food_security.<col>       — FoodSecurity (one-to-one)
      household.food_consumption.<col>    — FoodConsumption (one-to-one)
      household.head_member.<col>         — head Member, including reverse
                                            one-to-ones (.education, .employment)
      assets.<asset_type>.count           — AssetOwnership rows by type
      livestock.<livestock_type>.count    — Livestock rows by type
      member_count                        — int
      disabled_member_count               — int (Disability.wg_disability_flag)
      chronic_ill_member_count            — int (Health.chronic_illness_flag affirmative)
      school_age_out_of_school_count      — int (age 6–18 not currently attending)
      dependency_ratio                    — float

    The caller is expected to have prefetched the chain (see
    apps.pmt.services.recompute_for_household) so this helper is N+1-free.
    Per-Member reverse-OneToOnes are bulk-loaded here (4 queries total
    independent of member count) and attached to member instance dicts
    so the dotted-path resolver finds them without round-tripping.
    """
    # Importing here avoids a top-of-file circular: apps.data_management
    # → apps.security → apps.pmt → engine.py.
    from apps.data_management.models import (
        Disability,
        Education,
        Employment,
        Health,
    )

    # Filter the prefetched members cache in Python so we don't issue
    # a fresh .filter() query.
    members = [m for m in household.members.all() if not m.is_deleted]

    # Repeat-group children iterate the prefetched cache. The DSL
    # (ADR-0025) consumes these as LISTS — `count_where` /
    # `share_where` / `presence_in_collection` walk the rows. We also
    # keep dict-by-type slices on the returned record for any
    # legacy variable still using `assets.<type>.count` paths
    # (e.g. the v22001 draft seed; all-zero weights so harmless).
    assets_list = [a for a in household.assets.all() if not a.is_deleted]
    livestock_list = [
        ls for ls in household.livestock.all() if not ls.is_deleted
    ]
    crops_list = [
        c for c in (getattr(household, "crops", []) or []).all()
        if not getattr(c, "is_deleted", False)
    ] if hasattr(household, "crops") else []
    shocks_list = [
        s for s in (getattr(household, "shocks", []) or []).all()
        if not getattr(s, "is_deleted", False)
    ] if hasattr(household, "shocks") else []
    coping_list = [
        cs for cs in (getattr(household, "coping_strategies", []) or []).all()
        if not getattr(cs, "is_deleted", False)
    ] if hasattr(household, "coping_strategies") else []
    assets_by_type: dict[str, object] = {a.asset_type: a for a in assets_list}
    livestock_by_type: dict[str, object] = {
        ls.livestock_type: ls for ls in livestock_list
    }

    # Bulk-load per-member reverse-OneToOnes in 4 queries (not N×4).
    # Reverse-OneToOne accessors trigger a SELECT per missing row
    # otherwise; we pre-resolve them into id-keyed dicts and attach
    # them to each member instance's __dict__ so the descriptor is
    # bypassed at attribute lookup time.
    member_ids = [m.id for m in members]
    if member_ids:
        healths = {
            h.member_id: h
            for h in Health.objects.filter(member_id__in=member_ids)
        }
        disabilities = {
            d.member_id: d
            for d in Disability.objects.filter(member_id__in=member_ids)
        }
        educations = {
            e.member_id: e
            for e in Education.objects.filter(member_id__in=member_ids)
        }
        employments = {
            e.member_id: e
            for e in Employment.objects.filter(member_id__in=member_ids)
        }
        for m in members:
            # Direct __dict__ writes bypass Django's reverse-OneToOne
            # descriptor — None placeholders prevent the descriptor
            # firing a query on rows without a child.
            m.__dict__["health"] = healths.get(m.id)
            m.__dict__["disability"] = disabilities.get(m.id)
            m.__dict__["education"] = educations.get(m.id)
            m.__dict__["employment"] = employments.get(m.id)

    # Member-level aggregations.
    disabled = 0
    chronic_ill = 0
    school_age_out = 0
    under_15 = 0
    over_65 = 0
    working_age = 0
    for m in members:
        d = m.__dict__.get("disability")
        if d is not None and getattr(d, "wg_disability_flag", False):
            disabled += 1
        h = m.__dict__.get("health")
        if h is not None and getattr(h, "chronic_illness_flag", "") == "1":
            chronic_ill += 1
        age = getattr(m, "age_years", None) or 0
        if 6 <= age <= 18:
            e = m.__dict__.get("education")
            attending = getattr(e, "currently_attending", "") if e else ""
            if attending != "1":  # "1" = yes per the questionnaire
                school_age_out += 1
        if age < 15:
            under_15 += 1
        elif age > 65:
            over_65 += 1
        else:
            working_age += 1

    dependency_ratio = (
        (under_15 + over_65) / working_age if working_age > 0 else 0.0
    )

    # Reverse-OneToOne shortcuts on the record so the spec's DSL
    # paths (`dwelling.floor_material`, `utilities.lighting_energy`,
    # `head_member.education.highest_grade`) resolve without a
    # `household.` prefix. _safe_attr handles missing rows as None.
    head_member = _safe_attr(household, "head_member")
    return {
        # Legacy access — `household.X.Y` paths in older variables.
        "household": household,
        # DSL shortcuts (ADR-0025).
        "head_member": head_member,
        "dwelling":         _safe_attr(household, "dwelling"),
        "utilities":        _safe_attr(household, "utilities"),
        "livelihood":       _safe_attr(household, "livelihood"),
        "food_security":    _safe_attr(household, "food_security"),
        "food_consumption": _safe_attr(household, "food_consumption"),
        # Collections. assets + livestock keep their dict-by-type
        # shape (legacy code uses `assets.<type>.count` paths); the
        # DSL's `_collection()` helper iterates dict values so
        # `{"collection": "assets", "filter": {...}}` still walks the
        # rows. crops / shocks / coping_strategies are plain lists.
        "members":            members,
        "assets":             assets_by_type,
        "livestock":          livestock_by_type,
        "crops":              crops_list,
        "shocks":             shocks_list,
        "coping_strategies":  coping_list,
        # Materialised list slices for any DSL variable that needs a
        # guaranteed list — e.g. a future `count_where` on `assets_list`.
        "assets_list":        assets_list,
        "livestock_list":     livestock_list,
        # Scalars.
        "member_count":                     len(members),
        "disabled_member_count":            disabled,
        "chronic_ill_member_count":         chronic_ill,
        "school_age_out_of_school_count":   school_age_out,
        "dependency_ratio":                 dependency_ratio,
    }


def compute_pmt(household, model_version: PMTModelVersion) -> tuple[float, str, dict]:
    """Apply the model to a Household instance.

    Returns (score, band, inputs_snapshot) where inputs_snapshot logs
    each variable's raw value + transformed contribution for later
    audit.

    Variable shape dispatch (ADR-0025): each row in
    `model_version.variables` is either

      legacy  — {"variable": "<dotted.path>", "weight": …, "transform": …}
      DSL     — {"name": …, "weight": …, "feature": {"type": …, …}}

    A row carrying a `feature` block routes through the JSON DSL
    evaluator; everything else falls back to the legacy path+transform
    pipeline so older DRAFT versions (e.g. the v22001 detail-entity
    placeholder) keep scoring without a forced migration.
    """
    from apps.pmt.feature_evaluator import (
        FeatureEvaluationError,
        evaluate_feature,
    )

    snapshot: dict[str, dict] = {}
    score = float(model_version.intercept or 0)
    record = _household_features(household)
    for var in (model_version.variables or []):
        weight = float(var.get("weight", 0))
        name = var.get("name") or var.get("variable") or ""
        feature = var.get("feature") if isinstance(var, dict) else None
        if isinstance(feature, dict):
            # DSL path — evaluator owns the math.
            try:
                value = evaluate_feature(feature, record)
            except FeatureEvaluationError as exc:
                # One bad variable mustn't kill a household. Audit it,
                # contribute 0, keep scoring.
                value = 0.0
                snapshot[name] = {
                    "error": str(exc), "value": 0.0,
                    "weight": weight, "contribution": 0.0,
                }
                continue
            contribution = weight * value
            score += contribution
            snapshot[name] = {
                "value": value,
                "weight": weight,
                "contribution": contribution,
                "feature_type": feature.get("type"),
            }
        else:
            # Legacy path+transform shape.
            path = var.get("variable", "")
            transform = var.get("transform", "identity")
            raw = _get(record, path)
            transformed = _transform(raw, transform)
            contribution = weight * transformed
            score += contribution
            snapshot[path or name] = {
                "raw": raw if isinstance(raw, (int, float, str)) else str(raw),
                "transformed": transformed,
                "weight": weight,
                "contribution": contribution,
            }
    # derive_band now resolves the model_version's threshold rows
    # first and only falls back to fixed cutoffs when none exist —
    # the polymorphic dispatch keeps callers (here + tests) simple.
    band = derive_band(score, model_version)
    return score, band, snapshot
