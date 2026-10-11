"""Make the STAAC category labels the names STAAC actually sends.

Migration 0026 seeded these labels with the severity in brackets —
"Targeting and selection irregularity (Serious)" — so an operator
reading an unmapped finding could see how STAAC rates it without
opening a system they have no account for. Two things since then make
that wrong.

Severity is dropped. It was agreed to leave the exchange: a tier in
this registry is a routing ladder, not a severity, and there is
nowhere honest to put another system's rating. A suffix carrying a
value nothing reads is just a difference between our label and theirs.

And the label is now load-bearing. The partner API transmits
`grievance.category` as the configured category NAME and never the
code — deliberately, and the spec tells NSR not to derive a code from
the text. So the only thing this registry can match on is the name,
and matching it required `intake._code_for_label` to strip a suffix
this migration had added. A lookup that has to undo a decoration we
applied ourselves is a defect waiting for the day the decoration
changes.

After this the labels are character-for-character the `name` values
in STAAC's `rules.Category` table, loaded from
`specs/rules/taxonomy.json`, and an exact label match is all the
resolution needed.

`canonical_code` is untouched and still null on every option. What a
STAAC category MEANS here remains MGLSD's to approve; this only fixes
what it is called.
"""

from django.db import migrations

LIST_NAME = "staac_grievance_category"

# code -> the exact name STAAC's snapshot carries.
NAMES = {
    "C01": "Procurement irregularity",
    "C02": "Ghost beneficiaries, workers or projects",
    "C03": "Embezzlement or diversion of funds",
    "C04": "Bribery or solicitation",
    "C05": "Shoddy or incomplete works",
    "C06": "Delayed or non-receipt of funds or inputs",
    "C07": "Targeting and selection irregularity",
    "C08": "Payment not received or short payment",
    "C09": "Staff conduct or abuse of office",
    "C10": "Interference by officials",
    "C11": "Environmental and social",
    "C12": "GBV, SEA and SH",
    "C13": "Protected disclosure (whistleblower)",
    "C14": "Household or group dispute",
    "C15": "Information request or clarification",
    "C16": "Other",
}

# What 0026 wrote, so the reverse is exact rather than approximate.
SEVERITIES = {
    "C01": "Criminal", "C02": "Criminal", "C03": "Criminal",
    "C04": "Criminal", "C05": "Serious", "C06": "Serious",
    "C07": "Serious", "C08": "Serious", "C09": "Serious",
    "C10": "Serious", "C11": "Serious", "C12": "Criminal",
    "C13": "Criminal", "C14": "Administrative",
    "C15": "Administrative", "C16": "Administrative",
}


def _relabel(apps, mapping):
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    for code, label in mapping.items():
        ChoiceOption.objects.filter(
            choice_list__list_name=LIST_NAME, code=code,
        ).update(label=label)


def forwards(apps, schema_editor):
    _relabel(apps, NAMES)


def backwards(apps, schema_editor):
    _relabel(apps, {
        code: f"{name} ({SEVERITIES[code]})" for code, name in NAMES.items()
    })


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0027_seed_staac_complainant_gender"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
