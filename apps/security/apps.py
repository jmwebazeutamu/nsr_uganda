from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.security"
    label = "security"
    verbose_name = "Security (SEC)"

    def ready(self) -> None:
        # Register production-secret system checks.
        from . import checks  # noqa: F401
