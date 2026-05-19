from django.apps import AppConfig


class DataManagementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_management"
    label = "data_management"
    verbose_name = "Data Management (DAT)"

    def ready(self) -> None:
        # Attach get_<field>_label / get_<field>_labels methods to
        # Household and Member from the single-source-of-truth
        # choice_field_map (ADR-0010 §5).
        from .labels import attach_label_methods
        from .models import Household, Member
        attach_label_methods(Household, Member)
