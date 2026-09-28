"""Give F6 and F7 the registry column names they answer to.

`f6_gov_program_beneficiary` and `f7_programmes` carried only the form's
own spelling. The registry columns are `is_govt_programme_beneficiary`
and `programmes_benefited`, and neither appeared in the question's
aliases — so nothing could resolve a payload key to the column, and both
answers were dropped on promotion with no error. Every other employment
question already carried its column name; these two were the exceptions.

This states the correspondence that already existed between the form and
the schema. It does not create one: both columns are declared on
`apps.data_management.models.Employment` and both questions are in the
approved instrument.

Only these two questions are touched — a blanket reseed would also
rewrite the repeat-block work that migration 0011 settled.
"""
from django.db import migrations

from apps.intake.canonical_fields import QUESTION_ALIASES

QUESTIONS = ("f6_gov_program_beneficiary", "f7_programmes")


def reseed(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    updated = 0
    for name in QUESTIONS:
        aliases = list(QUESTION_ALIASES.get(name, []))
        if not aliases:
            continue
        for question in FormQuestion.objects.filter(name=name):
            question.payload_aliases = aliases
            question.canonical_field = aliases[0]
            question.save(update_fields=["payload_aliases", "canonical_field"])
            updated += 1
    print(f"\n  employment aliases reseeded on {updated} question(s)")


class Migration(migrations.Migration):
    dependencies = [("intake", "0013_bind_data_request_choice_lists")]
    operations = [migrations.RunPython(reseed, migrations.RunPython.noop)]
