from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    PartnerViewSet,
    partners_renewals,
    partners_sector_mix,
    partners_summary,
    partners_top_consumers,
)

router = DefaultRouter()
router.register(r"partners", PartnerViewSet, basename="partner")

# Dashboard endpoints (US-S23-009). Mounted at /api/v1/partners/<verb>/
# rather than under the ViewSet so they don't get list/retrieve routing.
urlpatterns = [
    path("partners/summary/",        partners_summary,        name="partners-summary"),
    path("partners/renewals/",       partners_renewals,       name="partners-renewals"),
    path("partners/sector-mix/",     partners_sector_mix,     name="partners-sector-mix"),
    path("partners/top-consumers/",  partners_top_consumers,  name="partners-top-consumers"),
    *router.urls,
]
