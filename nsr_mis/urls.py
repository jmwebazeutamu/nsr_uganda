from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from .views import console, home, manual

# OpenAPI schema + Swagger UI stay browsable without login (developer
# convenience). Every other DRF endpoint requires IsAuthenticated per
# the global DEFAULT_PERMISSION_CLASSES in settings.py.
schema_view = SpectacularAPIView.as_view(permission_classes=[AllowAny])
swagger_view = SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny])

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    # React design harness served same-origin so fetch() inherits the
    # Django session cookie (US-S11-013). Dev-only — production serves
    # the built React app through nginx with its own auth gateway.
    path("console/", console, name="console-home"),
    path("console/<path:path>", console, name="console-asset"),
    # User manual — MkDocs-built site under docs/user-manual/site/.
    # Same dev-convenience pattern as /console/; production should
    # serve these static files through nginx.
    path("manual/", manual, name="manual-home"),
    path("manual/<path:path>", manual, name="manual-asset"),
    # Admin Console — separate bundle, group-gated (HANDOFF §3.3).
    path("admin-console/", include("apps.admin_console.urls")),
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
    path("api/v1/grm/", include("apps.grievance.urls")),
    path("api/v1/ref/", include("apps.referral.urls")),
    path("api/v1/rpt/", include("apps.reporting.urls")),
    path("api/v1/drs/", include("apps.data_requests.urls")),
    # US-CHB-001 — chatbot assistant (ADR-0021). Router is empty
    # at scaffold time; viewsets register in CHB-004.
    path("api/v1/chatbot/", include("apps.chatbot.urls")),
    # US-DATA-EXP-001 — Data Explorer (ADR-0023). Every endpoint
    # gated by DATA_EXPLORER_ENABLED + the EXPLORER role; returns
    # 503 when the flag is off.
    path("api/v1/data-explorer/", include("apps.data_explorer.urls")),
    # US-CONSENT (Epic 19, ADR-0024) — Consent Management. Every endpoint
    # gated by CONSENT_MODULE_ENABLED; returns 503 when the flag is off.
    path("api/v1/consent/", include("apps.consent.urls")),
    # US-S23-008 — partners module (ADR-0011). Mounted at the bare
    # /api/v1/ prefix because the router itself owns "partners/".
    path("api/v1/", include("apps.partners.urls")),
    # Admin Console DRF surface — group-gated per IsAdminConsoleUser.
    path(
        "api/v1/admin/",
        include("apps.admin_console.admin_api_urls"),
    ),
]
