from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from .views import home

# OpenAPI schema + Swagger UI stay browsable without login (developer
# convenience). Every other DRF endpoint requires IsAuthenticated per
# the global DEFAULT_PERMISSION_CLASSES in settings.py.
schema_view = SpectacularAPIView.as_view(permission_classes=[AllowAny])
swagger_view = SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny])

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("api/schema/", schema_view, name="schema"),
    path("api/docs/", swagger_view, name="swagger-ui"),
    # Per-module routers — one OpenAPI tag per module.
    path("api/v1/reference-data/", include("apps.reference_data.urls")),
    path("api/v1/data-management/", include("apps.data_management.urls")),
    path("api/v1/security/", include("apps.security.urls")),
    path("api/v1/dqa/", include("apps.dqa.urls")),
    path("api/v1/ddup/", include("apps.ddup.urls")),
    path("api/v1/dih/", include("apps.ingestion_hub.urls")),
    path("api/v1/idv/", include("apps.identity_verification.urls")),
    path("api/v1/upd/", include("apps.update_workflow.urls")),
    path("api/v1/pmt/", include("apps.pmt.urls")),
    path("api/v1/intake/", include("apps.intake.urls")),
]
