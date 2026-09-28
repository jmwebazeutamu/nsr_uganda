"""Add `missing_data` to `pmt_variable_finding`.

`never_fires` answered "this variable has never moved a score" and left
three different reasons indistinguishable: the entity row was never
captured, the answer was blank, or the code never matched. On the live
v1 model eleven of the eighteen reported variables resolve perfectly
through the questionnaire and score zero only because `Dwelling` and
`Utilities` hold no rows at all.

Calling that a model defect sends it to the wrong desk. `missing_data`
says what is actually true — nobody captured this — and is toned
`quality` rather than `danger` for the same reason.

Adding an option to an active list follows migration 0021's precedent.
Forward-only per ADR-0003; the reverse removes only what it added.
"""

from django.db import migrations

LIST_NAME = "pmt_variable_finding"
CODE = "missing_data"
LABEL = "The data was never captured"


def seed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    choice_list = ChoiceList.objects.filter(list_name=LIST_NAME).first()
    if choice_list is None:
        return
    ChoiceOption.objects.get_or_create(
        choice_list=choice_list, code=CODE,
        defaults={
            "label": LABEL, "language": "en",
            "sort_order": 4, "status": "active",
        },
    )


def unseed(apps, schema_editor):
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    ChoiceOption.objects.filter(
        choice_list__list_name=LIST_NAME, code=CODE,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0024_seed_pmt_variable_finding"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
