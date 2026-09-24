"""Seed the pre-UBOS option codes as DEPRECATED, so history still reads.

Migration 0019 marks legacy options deprecated — it does not create
them. A database that never held the pre-2024 Kobo frame therefore has
no row for them at all, and a household captured under the old frame
renders as a bare number: "roof_material: 1" instead of "Iron sheets".

That is invisible on this box, which carried the codes before the UBOS
2024 frame landed and merely had them deprecated in place. It is not
invisible on a database built from migrations — CI, and the DR site —
where the labels simply do not exist.

`ChoiceOption.Status.DEPRECATED` is exactly this case: "past responses
must remain readable; new captures must not offer the code."
`resolve_label` reads deprecated options as a fallback; `resolve_options`,
which feeds capture controls, does not.

Codes and labels are the ones this registry actually used, exported from
the live catalogue rather than reconstructed.

Forward-only per ADR-0003; the reverse removes only the rows it added.
"""

from django.db import migrations

# list_name -> [(code, label, sort_order), ...]
LEGACY_OPTIONS = {
    "cooking_fuel": [
        ('1', 'Firewood', 1),
        ('2', 'Charcoal', 2),
        ('3', 'LPG / gas', 3),
        ('4', 'Electricity', 4),
        ('5', 'Kerosene / paraffin', 5),
        ('6', 'Crop residue / dung', 6),
        ('8', 'Other', 7),
    ],
    "dwelling_type": [
        ('1', 'Detached', 1),
        ('2', 'Semi-detached', 2),
        ('3', 'Flat', 3),
        ('4', 'Tenement', 4),
        ('5', 'Hut', 5),
        ('6', 'Tent', 6),
        ('8', 'Other', 7),
    ],
    "floor_material": [
        ('1', 'Cement / screed', 1),
        ('2', 'Tiles', 2),
        ('3', 'Earth — rammed', 3),
        ('4', 'Wood', 4),
        ('5', 'Bricks', 5),
        ('8', 'Other', 6),
    ],
    "not_working_reason": [
        ('1', 'Studying', 1),
        ('2', 'Household duties', 2),
        ('3', 'Illness / disability', 3),
        ('4', 'Retired / too old', 4),
        ('5', 'Too young', 5),
        ('6', 'Could not find work', 6),
        ('98', 'Other', 7),
    ],
    "roof_material": [
        ('1', 'Iron sheets', 1),
        ('2', 'Tiles', 2),
        ('3', 'Concrete', 3),
        ('4', 'Thatch / grass', 4),
        ('5', 'Mud / dung', 5),
        ('8', 'Other', 6),
    ],
    "wall_material": [
        ('1', 'Brick (burnt / unburnt)', 1),
        ('2', 'Mud', 2),
        ('3', 'Wood', 3),
        ('4', 'Iron sheets', 4),
        ('5', 'Concrete / stone', 5),
        ('6', 'Thatch / grass', 6),
        ('8', 'Other', 7),
    ],
    "waste_disposal": [
        ('1', 'Collected by service', 1),
        ('2', 'Burned', 2),
        ('3', 'Buried', 3),
        ('4', 'Composted', 4),
        ('5', 'Dumped in pit', 5),
        ('6', 'Dumped in open', 6),
        ('8', 'Other', 7),
    ],
    "work_frequency": [
        ('1', 'Full-time', 1),
        ('2', 'Part-time', 2),
        ('3', 'Occasional', 3),
        ('4', 'Seasonal', 4),
        ('5', 'Casual / day labour', 5),
    ],
}


def _seed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    for list_name, options in LEGACY_OPTIONS.items():
        for choice_list in ChoiceList.objects.filter(list_name=list_name):
            for code, label, sort_order in options:
                # Never resurrect a code the list already has — an
                # ACTIVE option with the same code is the current
                # meaning and must win.
                if choice_list.options.filter(code=code, language="en").exists():
                    continue
                ChoiceOption.objects.create(
                    choice_list=choice_list, code=code, label=label,
                    language="en", sort_order=sort_order,
                    status="deprecated",
                )


def _unseed(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")
    ChoiceOption = apps.get_model("reference_data", "ChoiceOption")
    for list_name, options in LEGACY_OPTIONS.items():
        codes = [code for code, _label, _order in options]
        ChoiceOption.objects.filter(
            choice_list__in=ChoiceList.objects.filter(list_name=list_name),
            code__in=codes, status="deprecated",
        ).delete()


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0020_fix_roman_numeral_casing")]
    operations = [migrations.RunPython(_seed, _unseed)]
