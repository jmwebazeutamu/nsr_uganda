from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import home

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Per-module routers — one OpenAPI tag per module.
    path("api/v1/reference-data/", include("apps.reference_data.urls")),
    path("api/v1/data-management/", include("apps.data_management.urls")),
    path("api/v1/security/", include("apps.security.urls")),
    path("api/v1/dqa/", include("apps.dqa.urls")),
    path("api/v1/ddup/", include("apps.ddup.urls")),
    path("api/v1/dih/", include("apps.ingestion_hub.urls")),
    path("api/v1/idv/", include("apps.identity_verification.urls")),
]
