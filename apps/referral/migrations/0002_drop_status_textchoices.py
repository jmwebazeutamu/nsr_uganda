"""Strip TextChoices from Referral.status + ProgrammeEnrolment.status,
align enrolment 'enrolled' → 'active' (US-S26-003 / ADR-0015).

Schema changes:
  - Both `status` columns become plain CharField(max_length=32),
    no `choices=` set. Codes are resolved against the
    referral_status / programme_enrolment_status ChoiceLists
    (US-S26-002 / US-S25-006).

Data migration:
  - Existing ProgrammeEnrolment rows with status='enrolled' are
    rewritten to 'active' per ADR-0015 §"Decision 4". Referral
    rows are NOT touched — on the referral side, 'enrolled' means
    "this referral became an enrolment", a terminal state.

Forward-only per ADR-0003. The reverse hook flips 'active' rows
back to 'enrolled'; the schema reverse is automatic.
"""

from __future__ import annotations

from django.db import migrations, models


def _rename_enrolled_to_active(apps, schema_editor):
    ProgrammeEnrolment = apps.get_model("referral", "ProgrammeEnrolment")
    ProgrammeEnrolment.objects.filter(status="enrolled").update(status="active")


def _rename_active_to_enrolled(apps, schema_editor):
    ProgrammeEnrolment = apps.get_model("referral", "ProgrammeEnrolment")
    ProgrammeEnrolment.objects.filter(status="active").update(status="enrolled")


class Migration(migrations.Migration):

    dependencies = [
        ("referral", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="programmeenrolment",
            name="status",
            field=models.CharField(default="active", max_length=32),
        ),
        migrations.AlterField(
            model_name="referral",
            name="status",
            field=models.CharField(default="sent", max_length=32),
        ),
        migrations.RunPython(
            _rename_enrolled_to_active,
            _rename_active_to_enrolled,
        ),
    ]
