"""Register STAAC's grievance categories, mapped to nothing yet.

NSR is to receive grievances from STAAC's GRM. STAAC classifies with
sixteen codes, C01-C16, versioned under its own ruleset; NSR classifies
with six — data_correction, exclusion_error, inclusion_error,
programme_issue, operator_conduct, other. The two vocabularies describe
overlapping but different things, and nothing in either system states
the correspondence.

So the codes are registered here and `canonical_code` is deliberately
left null on every one. `resolve_canonical_code` reads that as
"recognised, no approved binding" and the caller fails closed, which is
the honest state: NSR knows the code exists and does not yet know what
it means here.

Filling them in is not an engineering decision. "C07 Targeting and
selection irregularity" could be an exclusion_error or an
inclusion_error depending on which way the targeting went, and the
sample payload's narrative says omitted while its own severity field
says ADMINISTRATIVE against a category whose STAAC default is Serious.
Guessing would put a wrong category on a real complaint and make it
untriageable, so each binding is set through the ChoiceList approval
workflow by whoever owns both vocabularies.

Labels are STAAC's own, from specs/rules/taxonomy.json, so an operator
reading an unmapped finding sees the category the complainant was told
rather than a bare code.
"""

from django.db import migrations

LIST_NAME = "staac_grievance_category"

# code, STAAC label, STAAC default severity
CATEGORIES = [
    ("C01", "Procurement irregularity", "Criminal"),
    ("C02", "Ghost beneficiaries, workers or projects", "Criminal"),
    ("C03", "Embezzlement or diversion of funds", "Criminal"),
    ("C04", "Bribery or solicitation", "Criminal"),
    ("C05", "Shoddy or incomplete works", "Serious"),
    ("C06", "Delayed or non-receipt of funds or inputs", "Serious"),
    ("C07", "Targeting and selection irregularity", "Serious"),
    ("C08", "Payment not received or short payment", "Serious"),
    ("C09", "Staff conduct or abuse of office", "Serious"),
    ("C10", "Interference by officials", "Serious"),
    ("C11", "Environmental and social", "Serious"),
    ("C12", "GBV, SEA and SH", "Criminal"),
    ("C13", "Protected disclosure (whistleblower)", "Criminal"),
    ("C14", "Household or group dispute", "Administrative"),
    ("C15", "Information request or clarification", "Administrative"),
    ("C16", "Other", "Administrative"),
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
            "STAAC GRM grievance categories as received on the intake "
            "payload. canonical_code maps each to an "
            "apps.grievance.models.Category value and is set through "
            "the approval workflow, not seeded."
        ),
        status="active",
        author="migration:reference_data.0026",
        approved_by="migration:reference_data.0026",
    )
    for order, (code, label, severity) in enumerate(CATEGORIES, start=1):
        ChoiceOption.objects.create(
            choice_list=choice_list,
            code=code,
            # The severity rides in the label so an operator reading an
            # unmapped finding sees how STAAC rates it without a second
            # lookup into a system they cannot open.
            label=f"{label} ({severity})",
            language="en",
            sort_order=order,
            status="active",
            canonical_code=None,
        )


def unseed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceList.objects.filter(
        list_name=LIST_NAME, author="migration:reference_data.0026",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0025_seed_pmt_missing_data_finding"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
