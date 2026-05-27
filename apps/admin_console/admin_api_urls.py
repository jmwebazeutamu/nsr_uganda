"""URL conf for /api/v1/admin/* endpoints — mounted by nsr_mis/urls.py."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.admin_console.api import (
    PMTModelVersionAdminViewSet,
    pmt_dashboard,
    pmt_events,
    pmt_recompute_run_now,
    pmt_recompute_run_report,
    pmt_transforms,
)
from apps.admin_console.approvals_api import approvals_queue
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
from apps.admin_console.workflow_api import (
    ddup_decision_un_merge,
    ddup_pair_cross_household,
    ddup_pair_detail,
    ddup_pair_hold,
    ddup_pair_merge,
    ddup_pair_reject,
    ddup_pairs_list,
    ddup_queue_stats,
    ddup_version_clone,
    ddup_version_detail,
    ddup_versions_list,
    dqa_rule_clone,
    dqa_rule_detail,
    dqa_rule_preview,
    dqa_rule_reject,
    dqa_rule_sign,
    dqa_rule_submit,
    dqa_rules_list,
    upd_routing_detail,
    upd_routing_history,
    upd_routing_list,
    upd_routing_stats,
)

router = DefaultRouter()
router.register(
    r"pmt/versions",
    PMTModelVersionAdminViewSet,
    basename="admin-pmt-version",
)

urlpatterns = [
    # Unified Approvals queue — aggregates PENDING_APPROVAL items
    # across CL, DQA, PMT (one entry per item).
    path("approvals/", approvals_queue, name="admin-approvals-queue"),

    # PMT (sprint 22)
    path("pmt/dashboard/",            pmt_dashboard,        name="admin-pmt-dashboard"),
    path("pmt/recompute/run-now/",    pmt_recompute_run_now, name="admin-pmt-recompute-run-now"),
    path("pmt/recompute/runs/<str:run_id>/report/",
         pmt_recompute_run_report, name="admin-pmt-recompute-run-report"),
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

    # Workflow — UPD routing (sprint 23 Cat 2.1)
    path("workflow/upd-routing/",
         upd_routing_list, name="admin-workflow-routing-list"),
    path("workflow/upd-routing/history/",
         upd_routing_history, name="admin-workflow-routing-history"),
    path("workflow/upd-routing/stats/",
         upd_routing_stats, name="admin-workflow-routing-stats"),
    path("workflow/upd-routing/<str:change_type>/<str:pmt_relevant>/",
         upd_routing_detail, name="admin-workflow-routing-detail"),

    # Workflow — DQA rules (sprint 23 Cat 2.2)
    path("workflow/dqa/rules/",
         dqa_rules_list, name="admin-workflow-dqa-list"),
    path("workflow/dqa/rules/<str:rule_id>/",
         dqa_rule_detail, name="admin-workflow-dqa-detail"),
    path("workflow/dqa/rules/<str:rule_id>/clone/",
         dqa_rule_clone, name="admin-workflow-dqa-clone"),
    path("workflow/dqa/rules/<str:rule_id>/preview/",
         dqa_rule_preview, name="admin-workflow-dqa-preview"),
    path("workflow/dqa/rules/<str:rule_id>/v<int:version>/submit/",
         dqa_rule_submit, name="admin-workflow-dqa-submit"),
    path("workflow/dqa/rules/<str:rule_id>/v<int:version>/sign/",
         dqa_rule_sign, name="admin-workflow-dqa-sign"),
    path("workflow/dqa/rules/<str:rule_id>/v<int:version>/reject/",
         dqa_rule_reject, name="admin-workflow-dqa-reject"),

    # Workflow — DDUP (sprint 23 Cat 2.3)
    path("workflow/ddup/versions/",
         ddup_versions_list, name="admin-workflow-ddup-versions"),
    path("workflow/ddup/versions/<str:version_id>/",
         ddup_version_detail, name="admin-workflow-ddup-version-detail"),
    path("workflow/ddup/versions/<str:version_id>/clone/",
         ddup_version_clone, name="admin-workflow-ddup-version-clone"),
    path("workflow/ddup/pairs/",
         ddup_pairs_list, name="admin-workflow-ddup-pairs"),
    path("workflow/ddup/pairs/<str:pair_id>/",
         ddup_pair_detail, name="admin-workflow-ddup-pair-detail"),
    path("workflow/ddup/pairs/<str:pair_id>/merge/",
         ddup_pair_merge, name="admin-workflow-ddup-pair-merge"),
    path("workflow/ddup/pairs/<str:pair_id>/reject/",
         ddup_pair_reject, name="admin-workflow-ddup-pair-reject"),
    path("workflow/ddup/pairs/<str:pair_id>/hold/",
         ddup_pair_hold, name="admin-workflow-ddup-pair-hold"),
    path("workflow/ddup/pairs/<str:pair_id>/cross-household/",
         ddup_pair_cross_household, name="admin-workflow-ddup-pair-cross"),
    path("workflow/ddup/decisions/<str:decision_id>/un-merge/",
         ddup_decision_un_merge, name="admin-workflow-ddup-unmerge"),
    path("workflow/ddup/queue-stats/",
         ddup_queue_stats, name="admin-workflow-ddup-stats"),

    *router.urls,
]
