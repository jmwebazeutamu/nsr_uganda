"""Seed the PARISH-WALKIN SourceSystem + DPA + Connector.

US-S23-WALKIN — operators submitting from the household-capture
wizard at parish offices now land their submissions in DIH through
this dedicated source system, separate from the bulk KOBO connector.

The DPA carries no expiry (the parish channel is a permanent
ministry-owned intake path, not a partner data provision).
"""

from __future__ import annotations

from datetime import date

from django.db import migrations


PARISH_SOURCE_CODE = "PARISH-WALKIN"
PARISH_CONNECTOR_NAME = "parish-walkin"


def _seed(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    DataProvisionAgreement = apps.get_model(
        "ingestion_hub", "DataProvisionAgreement",
    )
    Connector = apps.get_model("ingestion_hub", "Connector")

    src, _ = SourceSystem.objects.get_or_create(
        code=PARISH_SOURCE_CODE,
        defaults={
            "name": "Parish Office Walk-in",
            "kind": "capi_walkin",  # closest existing enum value
            "description": (
                "Operator-driven submissions from parish offices via "
                "the household-capture wizard."
            ),
        },
    )
    DataProvisionAgreement.objects.get_or_create(
        reference="DPA-PARISH-WALKIN-2026",
        defaults={
            "source_system": src,
            "valid_from": date(2026, 1, 1),
            "valid_to": None,  # permanent ministry-owned intake path
            "purpose": (
                "Parish walk-in submissions from operators — internal "
                "ministry intake channel, no external data provider."
            ),
            "approved_by": "system",
        },
    )
    Connector.objects.get_or_create(
        source_system=src,
        name=PARISH_CONNECTOR_NAME,
    )


def _unseed(apps, schema_editor):
    Connector = apps.get_model("ingestion_hub", "Connector")
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    Connector.objects.filter(name=PARISH_CONNECTOR_NAME).delete()
    SourceSystem.objects.filter(code=PARISH_SOURCE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion_hub", "0003_kobocredential_and_run_type"),
    ]

    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
