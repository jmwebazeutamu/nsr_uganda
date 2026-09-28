"""Seed `pmt_variable_finding` — the vocabulary for PMT variable alarms.

The PMT dashboard needs to say that a variable carrying weight has never
once moved a score. That statement is a status, and a status is
reference data here: hardcoding `"never_fires"` in Python and its colour
in JSX is precisely the duplication `docs/ssot_register.md` forbids, and
the pattern that produced nineteen disagreeing status vocabularies in
the console already.

So the codes live here, `apps.pmt.findings` names them as constants
pinned to this list by a test, and the tone is resolved server-side from
`ui_tone`. The console renders a label and a tone and decides neither.

The list starts with two codes because Phase 0 can only answer "did it
ever fire". Phase 1 of `docs/pmt_verification_scope.md` extends it with
the causes — `missing_data`, `code_no_match`,
`operand_not_in_choice_list` and the rest — which need what the engine
observed per household. Extending a seeded list is a new version of it,
not an edit of this one (ADR-0010).

Forward-only per ADR-0003; the reverse removes only what it added.
"""

from django.db import migrations

LIST_NAME = "pmt_variable_finding"

OPTIONS = [
    (
        "never_fires",
        "Never fires",
        1,
    ),
    (
        "insufficient_sample",
        "Too few scored households to judge",
        2,
    ),
    (
        "operand_not_in_choice_list",
        "Tests codes the questionnaire does not carry",
        3,
    ),
]


def seed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")

    if ChoiceList.objects.filter(list_name=LIST_NAME).exists():
        return

    choice_list = ChoiceList.objects.create(
        list_name=LIST_NAME,
        version=1,
        description=(
            "How a PMT model variable stands against the scored "
            "population. Written by apps.pmt.findings; rendered by the "
            "PMT dashboard."
        ),
        status="active",
        author="migration:reference_data.0024",
        approved_by="migration:reference_data.0024",
    )
    for code, label, sort_order in OPTIONS:
        ChoiceOption.objects.create(
            choice_list=choice_list,
            code=code,
            label=label,
            language="en",
            sort_order=sort_order,
            status="active",
        )


def unseed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceList.objects.filter(
        list_name=LIST_NAME, author="migration:reference_data.0024",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0023_choiceoption_canonical_code"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
