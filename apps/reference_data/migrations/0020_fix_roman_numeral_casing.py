"""Title-cased Roman numerals in geographic-unit names.

The UBOS loader ran a title-case pass over every place name, which turned
Roman numerals into ordinary words:

    Bwaise Ii      Kisenyi Iii     Makerere Iii    Kololo Iv
    Nakasero Ii    Mulago Iii      Bukoto Ii       Naguru Ii

74 rows across parishes and sub-counties. An enumerator scanning a
dropdown for "Kisenyi II" does not find it, and a slip printed for a
household in Kololo IV reads "Kololo Iv".

It also breaks the ordering the operator sees. The dropdown sorts by
name, and "Kisenyi Iii" sorts before "Kisenyi I" because lowercase "ii"
sorts after uppercase "I" under the collation — so the list runs III, I,
II. Uppercasing the numeral is what fixes that too; there is no separate
sort change.

Only a token that is unambiguously a Roman numeral is touched:
  * it is not the first token of the name (a leading "Ii" would be
    suspicious, and none exist);
  * it matches II, III, IV, VI, VII, VIII, IX, XI, XII case-insensitively;
  * it is currently mixed-case, so an already-correct name is left alone.

Deliberately NOT matched: the single letters I, V and X. "I" as a
standalone token is already correct in every row that has one, and
uppercasing a bare "v" or "x" elsewhere in a Ugandan place name would be
a guess.

Idempotent — a second run finds no mixed-case numerals. Forward-only per
ADR-0003; the reverse is a no-op because restoring "Kololo Iv" is not a
state worth returning to.

No AuditEvent rows: a migration-time reference-data fix has no actor,
matching 0015, 0018 and 0019.

NOTE — a separate, unresolved problem in the same data. Kampala Central
Division's parish codes run …01.09 then …01.11, with no .10, and the
Kisenyi rows are code-shuffled against their alphabetical position
(.07 = Kisenyi III, .08 = Kisenyi I, .09 = Kisenyi II). Parish codes are
UBOS reference data with legal weight and this migration does NOT invent
a re-assignment for them. Tracked as OI-REFDATA-07: reconcile the parish
code frame against the UBOS source file.
"""

from __future__ import annotations

import re

from django.db import migrations

# II, III, IV, VI, VII, VIII, IX, XI, XII — never bare I, V or X.
ROMAN = re.compile(r"^(?:I{2,3}|IV|VI{0,3}|IX|XI{0,2})$", re.IGNORECASE)


def _fix_name(name: str) -> str:
    tokens = name.split(" ")
    out = []
    for index, token in enumerate(tokens):
        if index > 0 and token != token.upper() and ROMAN.match(token):
            out.append(token.upper())
        else:
            out.append(token)
    return " ".join(out)


def _uppercase_roman_numerals(apps, schema_editor):
    GeographicUnit = apps.get_model("reference_data", "GeographicUnit")
    updates = []
    for unit in GeographicUnit.objects.filter(name__regex=r"[Ii][ivIV]").iterator():
        fixed = _fix_name(unit.name)
        if fixed != unit.name:
            unit.name = fixed
            updates.append(unit)
    if updates:
        GeographicUnit.objects.bulk_update(updates, ["name"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("reference_data", "0019_retire_legacy_code_frames"),
    ]

    operations = [
        migrations.RunPython(_uppercase_roman_numerals, migrations.RunPython.noop),
    ]
