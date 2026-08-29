from django.apps import AppConfig


class UpdateWorkflowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.update_workflow"
    label = "update_workflow"
    verbose_name = "Update Workflow (UPD)"

    def ready(self) -> None:
        # Import the system-check module so its @register hook fires.
        from . import checks  # noqa: F401
