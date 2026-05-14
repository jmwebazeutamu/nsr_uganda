from django.apps import AppConfig


class IdentityVerificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.identity_verification"
    label = "identity_verification"
    verbose_name = "Identity Verification (IDV)"
