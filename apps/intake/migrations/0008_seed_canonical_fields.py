"""Seed FormQuestion.canonical_field from the stated mapping.

Forward-only in production per CLAUDE.md, but reversible here: the
reverse simply blanks the column, since nothing depended on it before
this migration ran.
"""
from django.db import migrations

from apps.intake.canonical_fields import QUESTION_TO_CANONICAL, COPING_PREFIXES


def seed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    updated = 0
    for question in FormQuestion.objects.all().iterator():
        canonical = QUESTION_TO_CANONICAL.get(question.name, "")
        if not canonical and question.name.startswith(COPING_PREFIXES):
            # Every L0x question scores one coping strategy on the same
            # frequency scale; the payload flattens them into rows of
            # {strategy_type, frequency}.
            canonical = "strategy_type"
        if canonical and question.canonical_field != canonical:
            question.canonical_field = canonical
            question.save(update_fields=["canonical_field"])
            updated += 1
    print(f"\n  canonical_field seeded on {updated} question(s)")


def unseed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    FormQuestion.objects.exclude(canonical_field="").update(canonical_field="")


class Migration(migrations.Migration):
    dependencies = [("intake", "0007_formquestion_canonical_field")]
    operations = [migrations.RunPython(seed, unseed)]
