# Generated for the DSA email-code signing fallback.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("partners", "0009_alter_programme_pmt_bands"),
    ]

    operations = [
        migrations.AddField(
            model_name="dsasignature",
            name="email_code_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dsasignature",
            name="email_code_hash",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="dsasignature",
            name="email_code_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
