"""Retire the legacy single-digit code frame; UBOS 2024 survives.

Six housing lists and two employment lists each carried two code frames
merged into one dropdown, so the capture wizard offered duplicate labels
the enumerator could not choose between ("Iron sheets" as both 1 and 11;
"Hut" as both 5 and 17). Two enumerators coding the same hut produced
different values.

The mapping — and, as importantly, what is NOT mappable and why — lives
in apps/reference_data/legacy_code_frames.py. Read that first.

This migration, per list:

1. Rewrites stored values for the EXACT pairs, across every model field
   in CODED_FIELDS including the *Version history tables (a household's
   history has to read the same way as its current row).
2. Marks EVERY legacy option `status='deprecated'` — both the exact ones
   (now unused) and the ambiguous ones (still referenced by rows). The
   choice-list bundle endpoint already filters to ACTIVE, so this is
   what removes them from the wizard; no UI change is needed.

Rows on an AMBIGUOUS legacy code are deliberately LEFT ALONE. There is
no UBOS 2024 code that means the same thing, and writing a guess into a
household's record would feed a fabricated answer into its PMT score.
The option row survives in `deprecated`, so those values stay
resolvable to their original label — which is exactly what
ChoiceOption's deprecation contract is for. `manage.py
report_legacy_choice_codes` lists what remains, for MGLSD sign-off.

Options are deprecated, never deleted: past responses must remain
interpretable (ChoiceOption docstring, ADR-0010).

Idempotent — re-running finds no ACTIVE legacy options and no legacy
stored values for the exact pairs. Forward-only per ADR-0003; the
reverse is a no-op because re-activating a frame that produced
uncodeable duplicates is not a state worth being able to return to.

No AuditEvent rows: a migration-time reference-data fix has no actor,
matching 0015 and 0018. See ADR-0032.
"""

from __future__ import annotations

from django.db import migrations

from apps.reference_data.legacy_code_frames import (
    CODED_FIELDS,
    EXACT,
    legacy_codes,
)


def _retire_legacy_frames(apps, schema_editor):
    ChoiceList = apps.get_model("reference_data", "ChoiceList")

    # 1. Rewrite stored values for the exact pairs.
    for app_label, model_name, field_name, list_name in CODED_FIELDS:
        mapping = EXACT.get(list_name) or {}
        if not mapping:
            continue
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover — model removed in a later app state
            continue
        for legacy_code, ubos_code in mapping.items():
            model.objects.filter(**{field_name: legacy_code}).update(
                **{field_name: ubos_code},
            )

    # 2. Deprecate every legacy option on every version of each list.
    for list_name in EXACT:
        codes = legacy_codes(list_name)
        if not codes:
            continue
        for choice_list in ChoiceList.objects.filter(list_name=list_name):
            choice_list.options.filter(
                code__in=codes, status="active",
            ).update(status="deprecated")


def _check_nothing_was_stranded(apps, schema_editor):
    """After the rewrite, no row may sit on an EXACT legacy code.

    Rows on an AMBIGUOUS code are expected and are not an error — they
    are the backlog `report_legacy_choice_codes` prints.
    """
    stranded = []
    for app_label, model_name, field_name, list_name in CODED_FIELDS:
        mapping = EXACT.get(list_name) or {}
        if not mapping:
            continue
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover
            continue
        n = model.objects.filter(**{f"{field_name}__in": list(mapping)}).count()
        if n:
            stranded.append(f"{model_name}.{field_name}: {n}")
    if stranded:
        raise RuntimeError(
            "legacy codes with an exact UBOS mapping survived the "
            f"rewrite: {', '.join(stranded)}",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0018_retire_duplicate_northern_region"),
        ("data_management", "0008_household_village_optional"),
    ]

    operations = [
        migrations.RunPython(_retire_legacy_frames, migrations.RunPython.noop),
        migrations.RunPython(_check_nothing_was_stranded, migrations.RunPython.noop),
    ]
