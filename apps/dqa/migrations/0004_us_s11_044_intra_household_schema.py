"""US-S11-044 — Intra-household DQA schema slice.

Adds:
- Severity expansion: block / reject_with_override / flag / info
  (legacy values blocking/warning/info get data-migrated below)
- DqaRule new fields: category / scope / expression_type / stages /
  applies_to / parameters / test_fixtures / message_template_i18n_key /
  parent_rule
- DqaEvaluation aggregate model

The migration is forward-only safe (additive on DqaRule + new model).
Severity choices on the model accept the new values; existing rule
rows in the dev DB get rewritten by `_migrate_legacy_severity` below.
The legacy values stay representable on the DB column (CharField has
no DB-side enum) so a rollback that re-introduces the old code is
non-destructive.
"""

import nsr_mis.common.fields
from django.db import migrations, models


_LEGACY_TO_NEW = {
    "blocking": "block",
    "warning": "flag",
    # "info" stays "info".
}


def _migrate_legacy_severity(apps, schema_editor):
    """Rewrite any existing DqaRule / DqaResult rows from the legacy
    three-value Severity vocabulary into the four-value one introduced
    by US-S11-044. Touches both tables because both carry a `severity`
    column."""
    DqaRule = apps.get_model("dqa", "DqaRule")
    DqaResult = apps.get_model("dqa", "DqaResult")
    for legacy, new in _LEGACY_TO_NEW.items():
        DqaRule.objects.filter(severity=legacy).update(severity=new)
        DqaResult.objects.filter(severity=legacy).update(severity=new)


def _rollback_legacy_severity(apps, schema_editor):
    """Inverse of the data migration. Useful when rolling back through
    this migration in dev — production migrations are forward-only per
    CLAUDE.md after Sprint 5, but this slice is reversible since it
    targets the dev / staging cycle."""
    DqaRule = apps.get_model("dqa", "DqaRule")
    DqaResult = apps.get_model("dqa", "DqaResult")
    inverse = {v: k for k, v in _LEGACY_TO_NEW.items()}
    for new, legacy in inverse.items():
        DqaRule.objects.filter(severity=new).update(severity=legacy)
        DqaResult.objects.filter(severity=new).update(severity=legacy)


class Migration(migrations.Migration):

    dependencies = [
        ("dqa", "0003_preview_run"),
    ]

    operations = [
        # New fields on DqaRule.
        migrations.AddField(
            model_name="dqarule",
            name="category",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=32,
                choices=[
                    ("intra_household", "Intra-household"),
                    ("field_level", "Field-level"),
                    ("geographic", "Geographic"),
                    ("identity", "Identity"),
                    ("duplicate", "Duplicate"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="scope",
            field=models.CharField(
                default="record", max_length=24,
                choices=[
                    ("field", "Field"),
                    ("record", "Record"),
                    ("household", "Household"),
                    ("cross_household", "Cross-household"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="expression_type",
            field=models.CharField(
                default="dsl", max_length=24,
                choices=[
                    ("dsl", "JSON DSL"),
                    ("python_callable", "Python callable"),
                    ("sql", "SQL"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="stages",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="applies_to",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="parameters",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="test_fixtures",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="message_template_i18n_key",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="dqarule",
            name="parent_rule",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.PROTECT,
                related_name="child_versions",
                to="dqa.dqarule",
            ),
        ),
        # Expand the severity column. CharField has no DB enum so we
        # only need to relax the max_length (the legacy choices were
        # 8 chars max; "reject_with_override" is 20). Choices set on
        # the model — Django renders this as a no-op for the DB but
        # the AlterField records the metadata change.
        migrations.AlterField(
            model_name="dqarule",
            name="severity",
            field=models.CharField(
                max_length=24,
                choices=[
                    ("block", "Block"),
                    ("reject_with_override", "Reject with override"),
                    ("flag", "Flag"),
                    ("info", "Info"),
                    # Legacy aliases kept during the US-S11-044 transition;
                    # data migration below rewrites existing rows. P2
                    # cleanup commit removes these.
                    ("blocking", "Blocking (deprecated → block)"),
                    ("warning", "Warning (deprecated → flag)"),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="dqaresult",
            name="severity",
            field=models.CharField(
                max_length=24,
                choices=[
                    ("block", "Block"),
                    ("reject_with_override", "Reject with override"),
                    ("flag", "Flag"),
                    ("info", "Info"),
                    # Legacy aliases kept during the US-S11-044 transition;
                    # data migration below rewrites existing rows. P2
                    # cleanup commit removes these.
                    ("blocking", "Blocking (deprecated → block)"),
                    ("warning", "Warning (deprecated → flag)"),
                ],
            ),
        ),
        # Data migration — rewrite legacy values in existing rows.
        migrations.RunPython(
            _migrate_legacy_severity, _rollback_legacy_severity,
        ),
        # New aggregate model.
        migrations.CreateModel(
            name="DqaEvaluation",
            fields=[
                (
                    "id",
                    nsr_mis.common.fields.ULIDField(
                        primary_key=True, serialize=False,
                    ),
                ),
                ("household_id", models.CharField(db_index=True, max_length=26)),
                (
                    "household_version",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "stage",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("dih_ingest", "DIH ingest (pre-promotion)"),
                            ("dih_promote", "DIH promote"),
                            ("registry_post_promote", "Registry post-promote"),
                        ],
                    ),
                ),
                (
                    "outcome",
                    models.CharField(
                        max_length=16,
                        choices=[
                            ("pass", "Pass"),
                            ("review", "Review (any FLAG)"),
                            ("block", "Block (any BLOCK / REJECT_WITH_OVERRIDE)"),
                        ],
                    ),
                ),
                ("results", models.JSONField(blank=True, default=list)),
                (
                    "evaluator_service_version",
                    models.CharField(default="1.0", max_length=32),
                ),
                ("actor", models.CharField(blank=True, max_length=64)),
                ("evaluated_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "DQA evaluation",
                "verbose_name_plural": "DQA evaluations",
                "indexes": [
                    models.Index(
                        fields=["household_id", "-evaluated_at"],
                        name="dqa_dqaeval_househo_893adb_idx",
                    ),
                    models.Index(
                        fields=["stage", "-evaluated_at"],
                        name="dqa_dqaeval_stage_cf7136_idx",
                    ),
                    models.Index(
                        fields=["outcome", "-evaluated_at"],
                        name="dqa_dqaeval_outcome_08e3db_idx",
                    ),
                ],
            },
        ),
    ]
