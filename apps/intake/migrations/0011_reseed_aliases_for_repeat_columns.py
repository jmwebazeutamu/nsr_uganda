"""Reseed aliases after moving repeat-block columns out of them.

Migration 0010 gave every coping question the aliases `strategy_type`
and `frequency`, and every K03/K04 question `shock_type`/`severity`. All
eighteen coping questions claimed the same two column names, so the
first one won and the column read "Engage in casual labor".

Those columns are now declared once in canonical_fields.REPEAT_COLUMNS
and are no longer aliases of any question. This reseeds so the database
matches.
"""
from django.db import migrations

from apps.intake.canonical_fields import COPING_PREFIXES, QUESTION_ALIASES


def reseed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    updated = 0
    for question in FormQuestion.objects.all().iterator():
        aliases = list(QUESTION_ALIASES.get(question.name, []))
        if not aliases and question.name.startswith(COPING_PREFIXES):
            # Kobo keys each coping strategy by the question name itself.
            # The wizard's {strategy_type, frequency} rows are resolved
            # through REPEAT_COLUMNS, not through here.
            aliases = [question.name]
        canonical = aliases[0] if aliases else ""
        if question.payload_aliases != aliases or question.canonical_field != canonical:
            question.payload_aliases = aliases
            question.canonical_field = canonical
            question.save(update_fields=["payload_aliases", "canonical_field"])
            updated += 1
    print(f"\n  aliases reseeded on {updated} question(s)")


class Migration(migrations.Migration):
    dependencies = [("intake", "0010_seed_payload_aliases")]
    operations = [migrations.RunPython(reseed, migrations.RunPython.noop)]
