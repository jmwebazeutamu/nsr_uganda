"""Seed FormQuestion.payload_aliases, and correct canonical_field.

Migration 0008 seeded canonical_field from a mapping built out of the
household review screen's old hardcoded label map. That map only ever
covered the parish wizard's field names, so every Kobo-shaped record —
which is all of the bulk-loaded ones — resolved nothing: `rooms_sleeping`,
`lighting_source`, `livelihood_source`, `self_care`, `main_job` and the
rest reported as unmapped and their codes rendered as bare numbers.

This reseeds from apps/intake/canonical_fields.py, which was rebuilt by
reading the keys real staged payloads of both shapes actually carry.
"""
from django.db import migrations

from apps.intake.canonical_fields import QUESTION_ALIASES

# Frozen here rather than imported: a migration is a historical record
# and must keep running after the app code it was written against moves
# on. COPING_ROW_ALIASES was removed from canonical_fields in 0011, when
# the repeat-block columns became declarations of their own.
COPING_PREFIXES = ("l01", "l02")
COPING_ROW_ALIASES = ["strategy_type", "frequency"]


def seed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    updated = 0
    for question in FormQuestion.objects.all().iterator():
        aliases = list(QUESTION_ALIASES.get(question.name, []))
        if not aliases and question.name.startswith(COPING_PREFIXES):
            # Kobo keys each coping strategy by the question name itself;
            # the wizard emits rows of {strategy_type, frequency}.
            aliases = [question.name, *COPING_ROW_ALIASES]
        if not aliases:
            continue
        canonical = aliases[0]
        if question.payload_aliases != aliases or question.canonical_field != canonical:
            question.payload_aliases = aliases
            question.canonical_field = canonical
            question.save(update_fields=["payload_aliases", "canonical_field"])
            updated += 1
    print(f"\n  payload_aliases seeded on {updated} question(s)")


def unseed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    FormQuestion.objects.exclude(payload_aliases=[]).update(payload_aliases=[])


class Migration(migrations.Migration):
    dependencies = [("intake", "0009_formquestion_payload_aliases")]
    operations = [migrations.RunPython(seed, unseed)]
