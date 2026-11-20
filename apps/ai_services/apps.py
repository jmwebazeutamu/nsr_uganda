from django.apps import AppConfig


class AiServicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_services"
    label = "ai_services"
    verbose_name = "AI services (ADR-0045)"

    def ready(self):
        from celery.signals import task_success

        from .tasks import rank_after_discovery

        task_success.connect(rank_after_discovery, dispatch_uid="ai_services.rank_after_discovery")
