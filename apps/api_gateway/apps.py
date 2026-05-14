from django.apps import AppConfig


class ApiGatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api_gateway"
    label = "api_gateway"
    verbose_name = "API Gateway (API)"
