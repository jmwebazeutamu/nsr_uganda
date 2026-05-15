from django.urls import path

from .views import (
    HouseholdsByPmtBand,
    HouseholdsBySubRegion,
    OpenGrievancesByTier,
    OverdueGrievancesByTier,
    PendingDedupPairsByTier,
    PmtScoreHistogram,
    SubmissionsPerDay,
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
    path("dashboards/submissions-per-day/",
         SubmissionsPerDay.as_view(),
         name="rpt-submissions-per-day"),
    path("dashboards/pending-dedup-pairs-by-tier/",
         PendingDedupPairsByTier.as_view(),
         name="rpt-pending-dedup-pairs-by-tier"),
    path("dashboards/pmt-score-histogram/",
         PmtScoreHistogram.as_view(),
         name="rpt-pmt-score-histogram"),
]
