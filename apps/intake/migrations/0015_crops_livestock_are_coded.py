"""Crops and livestock are coded questions, not prose.

H5 asked enumerators to "list crops grown in order of importance" and
H3 to "record number kept", both as free text. The registry stores
`Crop.crop_name` and `Livestock.livestock_type` as codes from the
`crop_name` and `livestock_type` lists, so every answer arrived as
something the registry could not store: "Maize, beans" and
"Goats 3; Chickens 8". `Crop` and `Livestock` were empty for every
household ever promoted.

Reaching a code from prose is guesswork — "Goats" is not "Goat" and
"Matooke" is not "Banana / matoke" — and `apps.ingestion_hub.services`
refuses to guess, so it recovered only the names that matched a label
exactly. Asking the question as a select removes the problem rather
than improving the guess.

The shape mirrors assets, which this form already does correctly:
`g15_assets_owned` is a select_multiple over `asset_type` and each
count is its own integer (`g15_count_radio` -> canonical `radio`). So
H3 becomes a select_multiple over `livestock_type` and gains one count
per kind, each relevant only when that kind was selected.

`h3_livestock_counts` keeps its question name — renaming it would
orphan every answer already collected — but its canonical field becomes
`livestock_kept`, because the value is no longer a count. The old name
stays as a payload alias so historical payloads still resolve.

This does not migrate any collected data. Answers already given as prose
remain prose and are still read by
`services._agriculture_free_text_rows`; only what the form asks from
here changes.
"""
from django.db import migrations

LIVESTOCK = [
    ("cattle", "Cattle"), ("goat", "Goat"), ("sheep", "Sheep"),
    ("pig", "Pig"), ("chicken", "Chicken"),
    ("other_poultry", "Other poultry"), ("rabbit", "Rabbit"),
    ("bees", "Bees"),
]


def code_questions(apps, schema_editor):
    FormQuestion = apps.get_model("intake", "FormQuestion")
    ChoiceList = apps.get_model("reference_data", "ChoiceList")

    def active_list(name):
        return ChoiceList.objects.filter(
            list_name=name, status="active",
        ).order_by("-version").first()

    crop_list = active_list("crop_name")
    stock_list = active_list("livestock_type")
    if crop_list is None or stock_list is None:
        # Without the lists there is nothing to bind to, and binding to
        # nothing would leave a select with no choices — worse than the
        # text field it replaced.
        print("\n  crop_name / livestock_type not seeded; skipped")
        return

    updated = 0
    for question in FormQuestion.objects.filter(name="h5_crops_grown"):
        question.type = "select_multiple"
        question.choice_list_ref = crop_list
        question.label = "H5. Crops grown, in order of importance"
        question.save(update_fields=["type", "choice_list_ref", "label"])
        updated += 1

    stock_questions = list(FormQuestion.objects.filter(name="h3_livestock_counts"))
    for question in stock_questions:
        question.type = "select_multiple"
        question.choice_list_ref = stock_list
        question.label = "H3. If yes, which livestock were kept on census night?"
        question.canonical_field = "livestock_kept"
        question.payload_aliases = ["livestock_kept", "livestock_counts"]
        question.save(update_fields=[
            "type", "choice_list_ref", "label",
            "canonical_field", "payload_aliases",
        ])
        updated += 1

    created = 0
    for question in stock_questions:
        section = question.section
        base = question.order_in_section
        for offset, (code, label) in enumerate(LIVESTOCK, start=1):
            _, made = FormQuestion.objects.get_or_create(
                section=section, name=f"h3_count_{code}",
                defaults={
                    "label": f"H3. Number kept - {label}",
                    "type": "integer",
                    "canonical_field": f"{code}_kept",
                    "payload_aliases": [f"{code}_kept"],
                    "relevant_expression":
                        "selected(${h3_livestock_counts}, '%s')" % code,
                    "order_in_section": base + offset,
                },
            )
            created += made
    print(f"\n  recoded {updated} question(s), added {created} livestock count(s)")


class Migration(migrations.Migration):

    dependencies = [
        ("intake", "0014_alias_employment_columns"),
        ("reference_data", "0025_seed_pmt_missing_data_finding"),
    ]

    operations = [
        migrations.RunPython(code_questions, migrations.RunPython.noop),
    ]
