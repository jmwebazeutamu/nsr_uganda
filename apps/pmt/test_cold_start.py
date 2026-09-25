"""A registry starting from empty can take its first household.

This file replaces the one that pinned the deadlock. What it described:

  * `pmt.0006` seeds v1 active with ``band_strategy="percentile"``;
  * a percentile model classifies from ``PMTBandThreshold`` rows and
    raises rather than falling back, because a percentile rank is not
    a score threshold and reinterpreting one would put households in
    the wrong band;
  * ``recompute_band_thresholds`` computes those rows from stored
    ``PMTResult.score`` values;
  * ``promote_stage_record`` called ``recompute_for_household``
    unguarded inside its atomic block.

So on an empty registry: no thresholds, so scoring raised, so the
promotion rolled back, so no score was stored, so the nightly job had
nothing to compute from. 76 ingestion_hub tests failed on it, and any
environment built from schema — a DR rebuild, a new instance, staging
— could not promote a single household.

Two changes break it, and neither invents band policy:

  1. **A household enters the registry whether or not PMT can band it
     yet.** Unscored was already a tolerated state — the same function
     returns None when there is no active model at all. Missing band
     policy is the same situation, and is now audited rather than
     raised through an atomic block.
  2. **The threshold job scores the population itself when it has no
     stored results to read.** `compute_score` exists separately from
     `compute_pmt` for exactly this: the bootstrap must not ask for
     the band it is computing the inputs for.

The policy is unchanged. Thresholds are still empirical, still derived
from the registry's own population, still the 10/20/30 ranks
`pmt.0006` approved.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _household():
    from apps.data_management.models import Household
    from apps.reference_data.models import GeographicUnit

    nodes, parent = {}, None
    for level in ("region", "sub_region", "district", "county",
                  "sub_county", "parish", "village"):
        nodes[level], _ = GeographicUnit.objects.get_or_create(
            level=level, code=f"CS-{level.upper()}",
            defaults={"name": level.title(), "parent": parent,
                      "effective_from": date(2026, 1, 1)},
        )
        parent = nodes[level]
    return Household.objects.create(urban_rural="2", **nodes)


def _active():
    from apps.pmt.models import PMTModelVersion

    return PMTModelVersion.objects.filter(status="active").first()


# --- the premise, so this file fails loudly if the seed changes ------

def test_the_seeded_active_model_still_uses_percentile_bands():
    active = _active()
    assert active is not None
    assert active.band_strategy == "percentile"
    assert active.band_cutoffs, "the model declares percentile RANKS"


def test_a_fresh_database_still_has_no_empirical_thresholds():
    """`pmt.0004` skips its backfill without results to compute from.
    That is unchanged — the fix is in what happens next, not here."""
    from apps.pmt.models import PMTBandThreshold, PMTResult

    assert not PMTResult.objects.exists()
    assert not PMTBandThreshold.objects.exists()


def test_banding_still_refuses_without_thresholds():
    """The enforcement that started this is intact. Fixing the cold
    start must not have quietly restored a fallback — a percentile
    rank used as a score cut is the wrong band, silently."""
    from apps.pmt.engine import PMTConfigurationError, derive_band

    with pytest.raises(PMTConfigurationError, match="no persisted empirical"):
        derive_band(40.0, _active())


# --- the canonical path ----------------------------------------------

def test_a_household_is_promoted_even_though_it_cannot_be_banded():
    """The first household into an empty registry.

    `recompute_for_household` returns None and audits why; it does not
    raise, so the caller's transaction survives.
    """
    from apps.pmt.models import PMTResult
    from apps.pmt.services import recompute_for_household
    from apps.security.models import AuditEvent

    household = _household()
    result = recompute_for_household(household, triggered_by="test", actor="test")

    assert result is None
    assert not PMTResult.objects.filter(household=household).exists()
    assert AuditEvent.objects.filter(
        action="recompute_skipped", entity_id=str(household.id),
    ).exists(), "the registry took a household unscored and left no record"


def test_promotion_does_not_roll_back_on_missing_band_policy():
    """The specific failure: 76 ingestion_hub tests, and every fresh
    deployment. Asserted against the service rather than the source, so
    it survives a refactor of either side."""
    from apps.pmt.services import recompute_for_household

    household = _household()
    # No raise is the assertion. If this regresses, every
    # promote_stage_record in an unbanded registry rolls back with it.
    assert recompute_for_household(
        household, triggered_by="dih_promote", actor="test",
    ) is None


def test_the_threshold_job_bootstraps_from_the_population():
    """The other half: the job no longer waits for rows that cannot
    arrive. It scores the promoted households itself."""
    from apps.pmt.models import PMTBandThreshold
    from apps.pmt.tasks import recompute_band_thresholds

    for _ in range(4):
        _household()

    recompute_band_thresholds(actor="test")

    rows = PMTBandThreshold.objects.filter(model_version=_active())
    assert rows.exists(), (
        "no thresholds computed — the registry is still unable to band "
        "its own population"
    )
    assert {r.band_name for r in rows} == set(_active().band_cutoffs)
    assert all(r.sample_size > 0 for r in rows)


def test_and_then_households_can_be_banded():
    """End to end: promote unscored, bootstrap, score."""
    from apps.pmt.models import PMTResult
    from apps.pmt.services import recompute_for_household
    from apps.pmt.tasks import recompute_band_thresholds

    household = _household()
    assert recompute_for_household(household, triggered_by="t", actor="t") is None

    recompute_band_thresholds(actor="test")

    result = recompute_for_household(household, triggered_by="t", actor="t")
    assert result is not None, "still unbandable after the bootstrap"
    assert result.band in {c[0] for c in PMTResult._meta.get_field("band").choices}


# --- the failure case -------------------------------------------------

def test_a_model_with_no_band_policy_at_all_is_still_refused():
    """Bootstrapping must not have become "score anything".

    A model declaring no bands has no policy to compute, and must stay
    unusable rather than acquiring one by accident.
    """
    from apps.pmt.models import ModelStatus, PMTBandThreshold, PMTModelVersion
    from apps.pmt.tasks import recompute_band_thresholds

    PMTModelVersion.objects.filter(status="active").update(
        status=ModelStatus.RETIRED,
    )
    bandless = PMTModelVersion.objects.create(
        version=9001, status=ModelStatus.ACTIVE, author="t",
        intercept=Decimal("0"), variables=[],
        band_strategy="percentile", band_cutoffs={},
    )
    _household()

    recompute_band_thresholds(actor="test")

    assert not PMTBandThreshold.objects.filter(model_version=bandless).exists()


def test_an_empty_registry_computes_nothing():
    """No households and no results means no thresholds — and no
    invented ones. The bootstrap reads a population; it does not
    manufacture one."""
    from apps.pmt.models import PMTBandThreshold
    from apps.pmt.tasks import recompute_band_thresholds

    recompute_band_thresholds(actor="test")

    assert not PMTBandThreshold.objects.exists()


# --- the same deadlock, one level up ----------------------------------

def test_a_new_percentile_model_can_be_activated():
    """Thresholds are computed for ACTIVE models only.

    So requiring them at activation made every percentile model
    impossible to activate: it needed thresholds to go active, and
    could not be given thresholds until it was. Activation checks that
    the model DECLARES its percentile ranks, which is the policy the
    threshold job works towards.
    """
    from apps.pmt.models import ModelStatus, PMTModelVersion
    from apps.pmt.services import activate_model_version

    version = PMTModelVersion.objects.create(
        version=9100, status=ModelStatus.PENDING_APPROVAL, author="analyst",
        intercept=Decimal("0"), variables=[],
        band_strategy="percentile",
        band_cutoffs={"extreme_poverty": 10, "poverty": 20,
                      "vulnerable": 30, "not_poor": 100},
    )
    activate_model_version(version, approver="reviewer")
    version.refresh_from_db()
    assert version.status == ModelStatus.ACTIVE


def test_a_percentile_model_declaring_no_ranks_is_refused():
    """The failure case. Declaring nothing leaves the threshold job
    with no policy to compute towards, so the model would score a
    population it can never classify."""
    from apps.pmt.models import ModelStatus, PMTModelVersion
    from apps.pmt.services import PMTApprovalError, activate_model_version

    version = PMTModelVersion.objects.create(
        version=9101, status=ModelStatus.PENDING_APPROVAL, author="analyst",
        intercept=Decimal("0"), variables=[],
        band_strategy="percentile", band_cutoffs={},
    )
    with pytest.raises(PMTApprovalError, match="declares no band_cutoffs"):
        activate_model_version(version, approver="reviewer")


def test_a_fixed_threshold_model_must_still_be_able_to_classify():
    """Unchanged for the strategy where the cutoffs ARE the policy."""
    from apps.pmt.models import ModelStatus, PMTModelVersion
    from apps.pmt.services import PMTApprovalError, activate_model_version

    version = PMTModelVersion.objects.create(
        version=9102, status=ModelStatus.PENDING_APPROVAL, author="analyst",
        intercept=Decimal("0"), variables=[],
        band_strategy="threshold", band_cutoffs={},
    )
    with pytest.raises(PMTApprovalError, match="no persisted band cutoffs"):
        activate_model_version(version, approver="reviewer")
