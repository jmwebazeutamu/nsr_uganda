from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.security"
    label = "security"
    verbose_name = "Security (SEC)"

    def ready(self) -> None:
        # Register production-secret system checks, and the m2m hook that
        # applies a role default scope when the role is granted (G7).
        from . import checks, signals  # noqa: F401
