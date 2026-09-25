from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("referral", "0004_swap_programme_fks_drop_legacy")]

    operations = [
        migrations.AddConstraint(
            model_name="programmeenrolment",
            constraint=models.UniqueConstraint(
                fields=("programme", "household"),
                name="programme_enrolment_unique_household",
            ),
        ),
    ]
