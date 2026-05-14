from django.apps import AppConfig


class DqaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dqa"
    label = "dqa"
    verbose_name = "Data Quality (DAT-DQA)"
