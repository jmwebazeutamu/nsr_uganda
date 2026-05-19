from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    DsaViewSet,
    PartnerViewSet,
    ProgrammeViewSet,
    partner_activity,
    partner_programmes,
    partner_usage,
    partners_renewals,
    partners_sector_mix,
    partners_summary,
    partners_top_consumers,
)

router = DefaultRouter()
router.register(r"partners", PartnerViewSet, basename="partner")
router.register(r"dsas", DsaViewSet, basename="dsa")
router.register(r"programmes", ProgrammeViewSet, basename="programme")

# Dashboard + sub-resource endpoints. Mounted at /api/v1/partners/<verb>/
# rather than under the ViewSets so they don't get list/retrieve routing.
urlpatterns = [
    path("partners/summary/",            partners_summary,        name="partners-summary"),
    path("partners/renewals/",           partners_renewals,       name="partners-renewals"),
    path("partners/sector-mix/",         partners_sector_mix,     name="partners-sector-mix"),
    path("partners/top-consumers/",      partners_top_consumers,  name="partners-top-consumers"),
    path("partners/<str:partner_id>/activity/", partner_activity,
         name="partner-activity"),
    path("partners/<str:partner_id>/usage/", partner_usage,
         name="partner-usage"),
    path("partners/<str:partner_id>/programmes/", partner_programmes,
         name="partner-programmes"),
    *router.urls,
]
