"""Registry-owned cross-domain bindings for programme eligibility options."""

from django.db import migrations, models


def seed_programme_eligibility_bindings(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    bindings = {
        "programme_pmt_band": {
            "poorest_20": "extreme_poverty",
            "poorest_40": "poverty",
            "middle_40": "vulnerable",
            "top_20": "not_poor",
        },
        "programme_sex_filter": {
            "any": "",
            "1": "1",
            "2": "2",
        },
    }
    for list_name, option_bindings in bindings.items():
        choice_list = ChoiceList.objects.filter(
            list_name=list_name, status="active",
        ).order_by("-version").first()
        if choice_list is None:
            continue
        for option_code, canonical_code in option_bindings.items():
            ChoiceOption.objects.filter(
                choice_list=choice_list, code=option_code,
            ).update(canonical_code=canonical_code)


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0022_reference_sequence")]

    operations = [
        migrations.AddField(
            model_name="choiceoption",
            name="canonical_code",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.RunPython(seed_programme_eligibility_bindings, migrations.RunPython.noop),
    ]
