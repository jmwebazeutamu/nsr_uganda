from django.urls import path

from .views import (
    HouseholdsByPmtBand,
    HouseholdsBySubRegion,
    OpenGrievancesByTier,
    OverdueGrievancesByTier,
)

urlpatterns = [
    path("dashboards/households-by-sub-region/",
         HouseholdsBySubRegion.as_view(),
         name="rpt-households-by-sub-region"),
    path("dashboards/households-by-pmt-band/",
         HouseholdsByPmtBand.as_view(),
         name="rpt-households-by-pmt-band"),
    path("dashboards/open-grievances-by-tier/",
         OpenGrievancesByTier.as_view(),
         name="rpt-open-grievances-by-tier"),
    path("dashboards/overdue-grievances-by-tier/",
         OverdueGrievancesByTier.as_view(),
         name="rpt-overdue-grievances-by-tier"),
]
