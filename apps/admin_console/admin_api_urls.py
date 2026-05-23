"""URL conf for /api/v1/admin/* endpoints — mounted by nsr_mis/urls.py."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.admin_console.api import (
    PMTModelVersionAdminViewSet,
    pmt_dashboard,
    pmt_events,
    pmt_recompute_run_now,
    pmt_transforms,
)
from apps.admin_console.refdata_api import (
    choice_list_clone,
    choice_list_option_detail,
    choice_list_options,
    choice_list_reject,
    choice_list_sign,
    choice_list_submit,
    choice_list_versions,
    choice_lists,
    geography_collection,
    geography_detail,
    geography_history,
    geography_import_ubos,
)

router = DefaultRouter()
router.register(
    r"pmt/versions",
    PMTModelVersionAdminViewSet,
    basename="admin-pmt-version",
)

urlpatterns = [
    # PMT (sprint 22)
    path("pmt/dashboard/",            pmt_dashboard,        name="admin-pmt-dashboard"),
    path("pmt/recompute/run-now/",    pmt_recompute_run_now, name="admin-pmt-recompute-run-now"),
    path("pmt/events/",               pmt_events,           name="admin-pmt-events"),
    path("pmt/transforms/",           pmt_transforms,       name="admin-pmt-transforms"),

    # Reference data — Choice lists (sprint 23 Cat 1.1)
    path("refdata/choice-lists/",
         choice_lists, name="admin-refdata-choice-lists"),
    path("refdata/choice-lists/<str:list_name>/versions/",
         choice_list_versions, name="admin-refdata-cl-versions"),
    path("refdata/choice-lists/<str:list_name>/clone/",
         choice_list_clone, name="admin-refdata-cl-clone"),
    path("refdata/choice-lists/<str:list_name>/versions/<int:version>/options/",
         choice_list_options, name="admin-refdata-cl-options"),
    path("refdata/choice-lists/<str:list_name>/versions/<int:version>/options/<str:code>/",
         choice_list_option_detail, name="admin-refdata-cl-option-detail"),
    path("refdata/choice-lists/<str:list_name>/versions/<int:version>/submit/",
         choice_list_submit, name="admin-refdata-cl-submit"),
    path("refdata/choice-lists/<str:list_name>/versions/<int:version>/sign/",
         choice_list_sign, name="admin-refdata-cl-sign"),
    path("refdata/choice-lists/<str:list_name>/versions/<int:version>/reject/",
         choice_list_reject, name="admin-refdata-cl-reject"),

    # Reference data — Geography (sprint 23 Cat 1.2)
    path("refdata/geography/",
         geography_collection, name="admin-refdata-geo"),
    path("refdata/geography/import-ubos/",
         geography_import_ubos, name="admin-refdata-geo-import-ubos"),
    path("refdata/geography/<str:level>/<str:code>/",
         geography_detail, name="admin-refdata-geo-detail"),
    path("refdata/geography/<str:level>/<str:code>/history/",
         geography_history, name="admin-refdata-geo-history"),

    *router.urls,
]
