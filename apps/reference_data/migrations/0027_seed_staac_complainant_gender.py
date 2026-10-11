"""Register STAAC's complainant gender values, mapped to nothing yet.

NSR records a person's sex as a code from the `sex` ChoiceList — `1`
Male, `2` Female — and `Member.sex` holds one. STAAC's intake payload
sends `complainant.gender`, which in STAAC is `parties.PartyBase.sex`:
an encrypted free-text field with no vocabulary behind it. Its intake
form offers three options (`apps.cases.models.DemographicSex`), so
those are the values to expect, but the column accepts anything an
officer types and a partner's form can change without telling us.

Hence a list rather than a translation in code. The three codes are
registered here and `canonical_code` is left null on every one, which
`resolve_canonical_code` reads as "recognised, no approved binding".
`apps.grievance.intake.resolve_gender` then returns the value as
unmapped, named, for the caller to report.

`female` -> `2` and `male` -> `1` look obvious, and that is exactly why
they are not seeded here. Every other external-to-canonical binding in
this registry is set through the ChoiceList approval workflow by
whoever owns both vocabularies, and a binding that writes a person's
recorded sex is not the one to make an exception for. Two systems'
data-sharing terms say which of their fields may cross and what it
becomes; a migration author guessing is how a vocabulary gap becomes
invisible. The mechanism migration 0023 added exists for this, and
setting these three is a minute's work for someone with the authority.

`not_said` is the interesting one and the reason seeding would have
been wrong: NSR's `sex` list has no "prefer not to say" code, so there
is nothing for it to bind to. Whoever owns this decides whether that
means a blank column or a new option on the `sex` list — a question
about the registry's own vocabulary, not about STAAC.
"""

from django.db import migrations

LIST_NAME = "staac_complainant_gender"

# STAAC's own intake options, from apps/cases/models.py DemographicSex.
GENDERS = [
    ("female", "Female"),
    ("male", "Male"),
    ("not_said", "Prefer not to say"),
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
            "Complainant gender as received on the STAAC GRM intake "
            "payload, where the field is free text. canonical_code "
            "maps each to a code on the `sex` list and is set through "
            "the approval workflow, not seeded."
        ),
        status="active",
        author="migration:reference_data.0027",
        approved_by="migration:reference_data.0027",
    )
    for order, (code, label) in enumerate(GENDERS, start=1):
        ChoiceOption.objects.create(
            choice_list=choice_list,
            code=code,
            label=label,
            language="en",
            sort_order=order,
            status="active",
            canonical_code=None,
        )


def unseed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceList.objects.filter(
        list_name=LIST_NAME, author="migration:reference_data.0027",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0026_seed_staac_grievance_category"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
