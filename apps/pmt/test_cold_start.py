"""A freshly deployed registry cannot score its first household.

This is not a test of a fix. It is the record of a gap found on
26 September 2026, pinned so that the fixture which works around it in
`apps/intake/tests.py` cannot quietly become the only description of
the system's behaviour.

The loop:

  * `pmt.0002` seeds the active model, v1, with
    ``band_strategy="percentile"``;
  * a percentile model classifies from ``PMTBandThreshold`` rows and,
    since the SSOT enforcement work, **raises** rather than falling
    back to ``band_cutoffs`` — correctly, because a percentile rank is
    not a score threshold and reinterpreting one as the other would
    put households in the wrong band;
  * ``pmt.0004`` deliberately skips its backfill when there are no
    ``PMTResult`` rows, leaving the nightly recompute to populate the
    table once scores arrive;
  * so on a fresh database there are no thresholds, and scoring
    raises;
  * and `ingestion_hub.services.promote_stage_record` calls
    ``recompute_for_household`` **unguarded, inside its atomic
    block** — so the raise rolls the promotion back;
  * so no household is ever promoted, no score is ever written, and
    the nightly job never has anything to compute thresholds from.

Production is not affected today: it holds 48 threshold rows and 354
results, put there before the enforcement landed. What is affected is
any environment built from schema — a DR rebuild, a new region's
instance, a fresh staging box, and every test database.

Resolving it is a policy decision and not one to take inside a test:

  * bootstrap thresholds from ``band_cutoffs`` at activation, treating
    the declared ranks as provisional score cuts until real ones
    exist; or
  * let the first N promotions score without a band, and backfill; or
  * make ``promote_stage_record`` tolerate a PMT failure — which
    trades a wrong band for a silently unscored household, and is the
    option the DDUP outage of 22 September argues against.

Whoever picks one should delete this file and replace it with a test
of the behaviour they chose.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_the_seeded_active_model_uses_percentile_bands():
    """The premise. If the seed ever changes strategy, the rest of
    this file is describing something that no longer happens."""
    from apps.pmt.models import PMTModelVersion

    active = PMTModelVersion.objects.filter(status="active").first()
    assert active is not None, "pmt.0002 should seed an active model"
    assert active.band_strategy == "percentile"
    assert active.band_cutoffs, "the model declares percentile RANKS"


def test_a_fresh_database_has_no_empirical_thresholds():
    """`pmt.0004` skips its backfill without results to compute from."""
    from apps.pmt.models import PMTBandThreshold, PMTResult

    assert not PMTResult.objects.exists()
    assert not PMTBandThreshold.objects.exists()


def test_a_fresh_deployment_cannot_score():
    """The gap itself.

    Asserting the CURRENT behaviour, not the desired one. When somebody
    fixes the bootstrap this test will fail, and that failure is the
    signal to delete this file — not to loosen the assertion.
    """
    from apps.pmt.engine import PMTConfigurationError, derive_band
    from apps.pmt.models import PMTModelVersion

    active = PMTModelVersion.objects.filter(status="active").first()

    with pytest.raises(PMTConfigurationError, match="no persisted empirical"):
        derive_band(40.0, active)


def test_promotion_does_not_guard_against_it():
    """Why the gap costs a promotion rather than just a band.

    `promote_stage_record` calls the recompute with no try/except, so
    a configuration error propagates out of an atomic block and takes
    the promotion with it. That is the shape of the DDUP outage on
    22 September: a contract enforced before the configuration it
    needs exists.
    """
    import inspect

    from apps.ingestion_hub import services

    source = inspect.getsource(services.promote_stage_record)
    assert "recompute_for_household" in source
    call_site = source[source.index("recompute_for_household"):]
    assert "except" not in call_site, (
        "promote_stage_record now guards the PMT recompute — if that is "
        "deliberate, this file's premise has changed and it should be "
        "rewritten around whatever was decided"
    )


def test_seeding_thresholds_is_what_makes_scoring_possible():
    """The workaround the intake fixtures use, stated once.

    Shows the loop is only a bootstrap problem: the moment thresholds
    exist, by any route, scoring works.
    """
    from apps.pmt.engine import derive_band
    from apps.pmt.models import PMTModelVersion
    from apps.pmt.test_helpers import seed_band_thresholds

    active = PMTModelVersion.objects.filter(status="active").first()
    seed_band_thresholds(active)

    from apps.pmt.models import PMTResult

    band = derive_band(40.0, active)
    assert band in {code for code, _label in PMTResult._meta.get_field("band").choices}
