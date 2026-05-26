"""Admin Console — unified Approvals queue.

A single GET endpoint that fans out across every module with a
DRAFT → PENDING_APPROVAL → ACTIVE lifecycle and returns the items
currently awaiting a second signature, so approvers don't have to
walk five admin sub-screens to find what's on their plate.

Covers: ChoiceList, DqaRule, PMTModelVersion.

DDUP versions are intentionally excluded — they don't expose a
submit/sign REST surface yet (apps.admin_console.workflow_api
only ships list/detail/clone for them). Add them here when the
lifecycle endpoints land.
"""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.admin_console.permissions import IsAdminConsoleUser
from apps.dqa.models import DqaRule, RuleStatus
from apps.pmt.models import ModelStatus, PMTModelVersion
from apps.reference_data.models import ChoiceList, ChoiceListStatus


def _iso(dt):
    return dt.isoformat() if dt else None


def _choice_list_row(cl: ChoiceList) -> dict:
    return {
        "kind": "choice_list",
        "kind_label": "Choice list",
        "id": str(cl.id),
        "name": cl.list_name,
        "label": cl.list_name.replace("_", " "),
        "version": cl.version,
        "author": cl.author,
        "submitted_at": _iso(cl.submitted_at),
        # CL + DQA share the same dual-approval shape: a single sign
        # call promotes PENDING_APPROVAL → ACTIVE (no-self-approve
        # enforced server-side by lifecycle.sign).
        "links": {
            "sign":   f"/api/v1/admin/refdata/choice-lists/{cl.list_name}/versions/{cl.version}/sign/",
            "reject": f"/api/v1/admin/refdata/choice-lists/{cl.list_name}/versions/{cl.version}/reject/",
        },
        "detail_screen": "admin-refdata-choicelists",
    }


def _dqa_rule_row(r: DqaRule) -> dict:
    return {
        "kind": "dqa_rule",
        "kind_label": "DQA rule",
        "id": str(r.id),
        "name": r.rule_id,
        # `description` is the only human-readable summary on DqaRule;
        # trim it for the table row.
        "label": (r.description or r.rule_id)[:120],
        "version": r.version,
        "author": r.author,
        "submitted_at": _iso(r.submitted_at),
        "links": {
            "sign":   f"/api/v1/admin/workflow/dqa/rules/{r.rule_id}/v{r.version}/sign/",
            "reject": f"/api/v1/admin/workflow/dqa/rules/{r.rule_id}/v{r.version}/reject/",
        },
        "detail_screen": "admin-workflow-dqa",
    }


def _pmt_version_row(mv: PMTModelVersion) -> dict:
    # PMT uses a three-step sign-off (MGLSD steward → UBOS DG →
    # author confirmation) tracked in PMTModelSignOff, so inline
    # sign/reject from the dashboard isn't viable. Surface the row
    # and link the approver into the PMT Configuration screen which
    # already implements the three-step UX.
    return {
        "kind": "pmt_model",
        "kind_label": "PMT model version",
        "id": str(mv.id),
        "name": f"PMT v{mv.version}",
        "label": mv.description or f"PMT model v{mv.version}",
        "version": mv.version,
        "author": mv.author,
        # PMTModelVersion has no submitted_at column; updated_at is
        # the closest proxy (it's bumped by submit_for_approval).
        "submitted_at": _iso(mv.updated_at),
        "links": {
            "configure": f"/api/v1/admin/pmt/versions/{mv.id}/",
        },
        "detail_screen": "admin-pmt-configuration",
    }


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def approvals_queue(request):
    """Return every item currently in PENDING_APPROVAL across modules.

    Response shape:
        {
          "count": <total>,
          "by_kind": {"choice_list": 2, "dqa_rule": 1, ...},
          "results": [<row>, ...]
        }
    """
    kind_filter = (request.query_params.get("kind") or "").strip()

    rows: list[dict] = []
    if not kind_filter or kind_filter == "choice_list":
        rows.extend(
            _choice_list_row(cl)
            for cl in ChoiceList.objects
            .filter(status=ChoiceListStatus.PENDING_APPROVAL)
            .order_by("submitted_at", "id")
        )
    if not kind_filter or kind_filter == "dqa_rule":
        rows.extend(
            _dqa_rule_row(r)
            for r in DqaRule.objects
            .filter(status=RuleStatus.PENDING_APPROVAL)
            .order_by("submitted_at", "id")
        )
    if not kind_filter or kind_filter == "pmt_model":
        rows.extend(
            _pmt_version_row(mv)
            for mv in PMTModelVersion.objects
            .filter(status=ModelStatus.PENDING_APPROVAL)
            .order_by("-version")
        )

    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1

    return Response({
        "count": len(rows),
        "by_kind": by_kind,
        "results": rows,
    })
