"""Band configuration for PMT test fixtures, taken from the registry.

A PMT model cannot be activated, and cannot score, without a persisted
band policy — `services._validate_band_configuration` calls the same
`derive_band` that scoring uses, so activation fails exactly where
scoring would. That is deliberate: band policy belongs to the approved
model, not to application code.

It also means a fixture that builds a bare `PMTModelVersion` and
activates it now fails. The temptation is to paste four numbers into
each test. That would put band policy back into code, in as many
copies as there are fixtures, which is the thing the enforcement
exists to prevent.

So these read the policy that migrations already seed:

  * `pmt.0002` seeds a draft model with fixed `band_cutoffs`;
  * that model's cutoffs and band names are the canonical scheme.

Band names come from `PMTResult.Band` in every case — never a string
literal — so a fixture cannot invent a band the registry has no column
for.
"""

from __future__ import annotations

from decimal import Decimal


def canonical_band_cutoffs() -> dict[str, int]:
    """The seeded fixed-threshold scheme, from the database.

    Raises rather than returning a default: a test database with no
    seeded model is a broken migration chain, and inventing cutoffs
    here would hide it.
    """
    from apps.pmt.models import PMTModelVersion

    seeded = (
        PMTModelVersion.objects
        .exclude(band_cutoffs={})
        .filter(band_strategy="threshold")
        .order_by("version")
        .first()
    )
    if seeded is None:
        raise AssertionError(
            "no seeded PMTModelVersion carries band_cutoffs — pmt.0002 "
            "should have created one; the migration chain is incomplete",
        )
    return dict(seeded.band_cutoffs)


def make_model_version(**overrides):
    """A PMTModelVersion that can actually be activated and can score.

    Fixed-threshold by default, because that needs nothing beyond the
    model row itself — a percentile model additionally requires
    `PMTBandThreshold` rows, which is a different fixture and a
    different thing to be testing.
    """
    from apps.pmt.models import ModelStatus, PMTModelVersion

    defaults = {
        "status": ModelStatus.DRAFT,
        "author": "analyst@nsr.go.ug",
        "intercept": Decimal("0"),
        "variables": [],
        "band_strategy": "threshold",
        "band_cutoffs": canonical_band_cutoffs(),
    }
    defaults.update(overrides)
    return PMTModelVersion.objects.create(**defaults)


def seed_band_thresholds(model_version, *, actor: str = "test-fixture"):
    """Give a PERCENTILE model the empirical thresholds it requires.

    Derived from the model's own percentile ranks so the fixture
    cannot disagree with the policy it is standing in for: rank 30
    becomes threshold 30.0. The absolute values do not matter to a
    classifier test; that they exist, and that there is one per
    declared band, does.
    """
    from apps.pmt.models import PMTBandThreshold

    ranks = model_version.band_cutoffs or canonical_band_cutoffs()
    return [
        PMTBandThreshold.objects.create(
            model_version=model_version,
            band_name=band,
            percentile_rank=float(rank),
            score_threshold=Decimal(str(float(rank))),
            # How many scored households the threshold was computed
            # from. Not zero: a threshold computed from no sample is
            # not a threshold, and a fixture claiming one would be
            # asserting something the recompute job could never
            # produce.
            sample_size=1,
            computed_by=actor,
        )
        for band, rank in sorted(ranks.items(), key=lambda kv: float(kv[1]))
    ]
