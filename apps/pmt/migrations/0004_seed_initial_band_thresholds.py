"""US-S22-PMT-BAND-THRESHOLD — backfill thresholds once on upgrade.

On a fresh deploy with no PMTResults this is a no-op; the daily beat
job (apps.pmt.tasks.recompute_band_thresholds_task) starts populating
the table when scores arrive. On a populated DB (existing
PMTResults), this runs the same recompute logic once at migrate time
so derive_band picks up empirical thresholds immediately — without
waiting for the next 02:00 EAT beat window.

Idempotent — re-running appends fresh rows (the task is append-only
by design), but the migration framework only runs it once per
database.

Forward-only per ADR-0003. Reverse drops every row in the table.
"""

from __future__ import annotations

from django.db import migrations


def _backfill(apps, schema_editor):
    # Migration-safe shortcut: if no PMTResult rows exist yet (fresh
    # deploy) skip the recompute entirely — the daily beat job will
    # populate when scores arrive. This also keeps the migration
    # robust against any FUTURE schema additions to PMTModelVersion:
    # without this guard, importing `recompute_band_thresholds` runs
    # ORM queries with the live model class, which references columns
    # the historical schema doesn't yet have.
    PMTResult = apps.get_model("pmt", "PMTResult")
    if not PMTResult.objects.exists():
        return
    # Late-import the task helpers — apps.pmt.tasks pulls in
    # apps.security.audit which is fine post-migrate but not at
    # import time on a fresh schema.
    from apps.pmt.tasks import recompute_band_thresholds
    recompute_band_thresholds(actor="migration-0004")


def _wipe(apps, schema_editor):
    PMTBandThreshold = apps.get_model("pmt", "PMTBandThreshold")
    PMTBandThreshold.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pmt", "0003_pmt_band_threshold_table"),
    ]

    operations = [
        migrations.RunPython(_backfill, _wipe),
    ]
