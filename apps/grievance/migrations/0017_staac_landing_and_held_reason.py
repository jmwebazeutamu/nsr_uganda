"""Land STAAC snapshots in the registry's landing table, not a column.

`StaacHandover` carried its own `snapshot` JSON column, justified on
the grounds that `RawLanding` is FK-bound to a `ConnectorRun` and no
run existed for a partner the registry reached outside DIH's pipeline.

That justification was true and is now removed: a `SourceSystem` and
`Connector` are registered for STAAC here, so the pull opens a real
`ConnectorRun` and lands each snapshot through `land_payload`. Three
things follow, and each was a finding against the first version:

* one landing table answers "what arrived from outside, when, and in
  which run" for every external payload, instead of two;
* `start_connector_run` enforces AC-DIH-DPA-REQUIRED, so a partner's
  personal data cannot be received at all until an agreement covering
  that source is recorded in the registry's own register — rather
  than the registry taking the partner's word for which agreement
  authorises the disclosure;
* run accounting is `ConnectorRun`'s counters, which are queryable
  and have an admin, instead of a dataclass that lived for the length
  of one command.

Registering the source does NOT put grievances through DIH's staging
pipeline. ADR-0044 stands and is amended to say which half is which:
DIH owns the registry of sources, agreements, runs and landings; what
a grievance skips is `StageRecord` — the DQA/IDV/dedup ladder and
promotion to DAT, every step of which is a household operation.

No DPA is seeded. An agreement is something somebody signs, so its
absence must block, and that is the point of the gate.

Safe as a plain schema change: `StaacHandover` has no rows in any
environment (the pull has never been run against a live partner), so
there is nothing to migrate from the dropped column.
"""

from django.db import migrations, models
import django.db.models.deletion

SOURCE_CODE = "STAAC_GRM"
CONNECTOR_NAME = "staac-partner-api"


def seed_source(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    Connector = apps.get_model("ingestion_hub", "Connector")

    source, _ = SourceSystem.objects.get_or_create(
        code=SOURCE_CODE,
        defaults={
            "name": "STAAC GRM (Inspectorate of Government)",
            "kind": "partner_mis",
            "description": (
                "Approved grievance handovers pulled from STAAC's partner "
                "API. Registered here for provenance, agreement and run "
                "accounting; the records it brings are grievances and do "
                "not enter DIH's staging pipeline. See ADR-0044."
            ),
            "is_active": True,
            # The registry blocks on an unmapped choice value for UBOS
            # only; a STAAC category it cannot map is held by the
            # grievance intake itself, with the snapshot kept.
            "blocks_on_unmapped_choice_value": False,
        },
    )
    Connector.objects.get_or_create(
        source_system=source, name=CONNECTOR_NAME,
        defaults={"config": {}, "is_active": True},
    )


def unseed_source(apps, schema_editor):
    SourceSystem = apps.get_model("ingestion_hub", "SourceSystem")
    Connector = apps.get_model("ingestion_hub", "Connector")
    Connector.objects.filter(
        source_system__code=SOURCE_CODE, name=CONNECTOR_NAME,
    ).delete()
    SourceSystem.objects.filter(code=SOURCE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("grievance", "0016_drop_unreachable_handover_outcome"),
        ("ingestion_hub", "0009_source_system_blocks_on_unmapped"),
    ]

    operations = [
        migrations.RunPython(seed_source, unseed_source),
        migrations.RemoveField(model_name="staachandover", name="snapshot"),
        migrations.AddField(
            model_name="staachandover",
            name="raw_landing",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="staac_handover",
                to="ingestion_hub.rawlanding",
            ),
        ),
        migrations.AddField(
            model_name="staachandover",
            name="held_reason",
            field=models.CharField(
                blank=True, db_index=True, max_length=32,
                choices=[
                    ("unknown_category", "Category not in the registered list"),
                    ("unbound_category", "Category registered, no approved binding"),
                    ("unresolved_place", "Place names no GeographicUnit"),
                    ("unverified_agreement", "No data-provision agreement covers it"),
                    ("refused", "Refused for another reason"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="staachandover", name="held_choice_list",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="staachandover", name="held_source_code",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddIndex(
            model_name="staachandover",
            index=models.Index(
                fields=["held_reason", "held_source_code"],
                name="grievance_s_held_re_a8b0f7_idx",
            ),
        ),
    ]
