"""Move the DRS field policy into the canonical data dictionary.

The source catalogue is imported only while this historical migration runs.
Afterwards runtime DRS code reads ``DataRequestFieldDefinition`` rows, not
the former application-level list.
"""

import django.db.models.deletion
import nsr_mis.common.fields
from django.db import migrations, models


def seed_data_request_definitions(apps, schema_editor):
    # Deliberately import the migration bridge rather than duplicate the old
    # catalogue in a second file.  The bridge is removed from runtime use by
    # the accompanying application change.
    from apps.data_requests.builder_schema import bootstrap_catalogue_for_migration

    Definition = apps.get_model("intake", "DataRequestFieldDefinition")
    FormQuestion = apps.get_model("intake", "FormQuestion")
    ChoiceList = apps.get_model("reference_data", "ChoiceList")

    questions_by_alias = {}
    for question in FormQuestion.objects.exclude(canonical_field="").iterator():
        for alias in [question.canonical_field, *(question.payload_aliases or [])]:
            questions_by_alias.setdefault(alias, question)
    choice_lists = {
        row.list_name: row
        for row in ChoiceList.objects.filter(status="active").order_by("-version")
    }

    for entry in bootstrap_catalogue_for_migration():
        path = entry["key"]
        leaf = path.rsplit(".", 1)[-1]
        question = questions_by_alias.get(leaf)
        list_name = ""
        source = entry.get("options_source", "")
        if source.startswith("choice_list?name="):
            list_name = source.partition("=")[2]
        choice_list = choice_lists.get(list_name)
        Definition.objects.update_or_create(
            registry_path=path,
            defaults={
                "label": entry["label"],
                "data_type": entry["type"],
                "disclosure_group": entry["group"],
                "privacy_class": entry.get("sensitivity", ""),
                "source_model": "",
                "source_field": leaf,
                "question_id": getattr(question, "id", None),
                "choice_list_ref_id": getattr(choice_list, "id", None),
                "options_source": source,
                "requires_special_scope": bool(entry.get("requires_special_scope")),
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("intake", "0011_reseed_aliases_for_repeat_columns"),
        ("reference_data", "0023_choiceoption_canonical_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataRequestFieldDefinition",
            fields=[
                ("id", nsr_mis.common.fields.ULIDField(primary_key=True, serialize=False)),
                ("registry_path", models.CharField(max_length=192, unique=True)),
                ("label", models.CharField(max_length=256)),
                ("data_type", models.CharField(max_length=24)),
                ("disclosure_group", models.CharField(max_length=128)),
                ("privacy_class", models.CharField(blank=True, max_length=64)),
                ("source_model", models.CharField(blank=True, max_length=128)),
                ("source_field", models.CharField(blank=True, max_length=128)),
                ("options_source", models.CharField(blank=True, max_length=256)),
                ("requires_special_scope", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("choice_list_ref", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="data_request_definitions", to="reference_data.choicelist")),
                ("question", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="data_request_definitions", to="intake.formquestion")),
            ],
            options={
                "verbose_name": "Data request field definition",
                "verbose_name_plural": "Data request field definitions",
                "ordering": ("disclosure_group", "registry_path"),
                "indexes": [models.Index(fields=["is_active", "disclosure_group"], name="intake_data_is_acti_f45fcf_idx")],
            },
        ),
        migrations.RunPython(seed_data_request_definitions, migrations.RunPython.noop),
    ]
