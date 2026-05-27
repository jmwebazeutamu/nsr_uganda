"""US-S11-044 — Fields the intra-household DQA evaluator reads.

- `Household.reported_household_size` — operator-captured at intake;
  AC-MEMBER-COUNT-MATCH compares it against the actual member roster.
  Populated by DIH promotion from canonical_payload.interview.hh_size.

- `Member.orphan_flag` — AC-ORPHAN-FLAG asserts this is True when
  both parents are deceased and the member is under 18. Nullable so
  historical rows captured before this field existed don't trip the
  rule.

Additive + reversible. Existing rows get null defaults — no data
migration needed because both rules use null-checks in the DSL
expressions.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_management", "0008_household_village_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="household",
            name="reported_household_size",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="member",
            name="orphan_flag",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
