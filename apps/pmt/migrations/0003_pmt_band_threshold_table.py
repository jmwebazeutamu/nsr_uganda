"""US-S22-PMT-BAND-THRESHOLD — create PMTBandThreshold.

The active PMT model's band_cutoffs were stored as fixed score
thresholds. MGLSD's policy directive (O-03 answer pack, 2026-05-21)
says the 30% national eligibility cutoff is a population percentile,
not a score value — the actual score-threshold shifts as the
registry grows and recalibrates.

This migration adds the empirical-threshold table; the recompute job
in apps.pmt.tasks fills it daily, and apps.pmt.engine.derive_band
pin-classifies a score against the most recent row per band.

Append-only — every recompute writes new rows so the history is
queryable for audit + calibration-drift tracking. Old rows are kept
indefinitely; cleanup is a separate retention task.

Forward-only per ADR-0003. Reverse drops the table; derive_band
falls back to PMTModelVersion.band_cutoffs in that case.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

import nsr_mis.common.fields


class Migration(migrations.Migration):

    dependencies = [
        ("pmt", "0002_seed_draft_detail_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMTBandThreshold",
            fields=[
                ("id", nsr_mis.common.fields.ULIDField(
                    editable=False, max_length=26, primary_key=True, serialize=False,
                )),
                ("band_name", models.CharField(max_length=32)),
                ("score_threshold", models.DecimalField(
                    decimal_places=6, max_digits=10,
                )),
                ("percentile_rank", models.PositiveSmallIntegerField()),
                ("sample_size", models.PositiveIntegerField()),
                ("computed_at", models.DateTimeField(auto_now_add=True)),
                ("computed_by", models.CharField(default="celery-beat", max_length=64)),
                ("model_version", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="band_thresholds",
                    to="pmt.pmtmodelversion",
                )),
            ],
            options={
                "verbose_name": "PMT band threshold",
                "indexes": [
                    models.Index(
                        fields=["model_version", "band_name", "-computed_at"],
                        name="pmt_pmtband_model_v_b_band_n_idx",
                    ),
                ],
            },
        ),
    ]
