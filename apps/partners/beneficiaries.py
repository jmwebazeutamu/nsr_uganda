"""GET /api/v1/beneficiaries/ — per-programme enrolment ledger
(US-S26-006 / ADR-0015 §"Decision 5").

One row per (household, programme) tuple, synthesised from:
  • apps.referral.ProgrammeEnrolment — explicit enrolment rows
    carry their own status (active / suspended / pending / exited
    via the programme_enrolment_status ChoiceList).
  • apps.referral.Referral — referrals that are still in flight
    (status `sent` or `accepted`) with no enrolment yet project as
    status='pending' on this surface. This is the derived state
    ADR-0015 §"Decision 4" describes.

ABAC: combined partner + geographic. A partner-affiliated user
sees only beneficiaries of their partner's programmes. A
geographically-scoped operator sees beneficiaries whose
households fall under their sub_regions. National / superuser
see all. Users with NO scope fail closed (empty).

Pagination is page-number for now (DRF default page_size=50);
cursor-paginated variant lands when production scale arrives.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
)
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination

from apps.reference_data.services import resolve_label
from apps.referral.models import ProgrammeEnrolment, Referral
from apps.security.models import OperatorScope, ScopeLevel

from .models import Partner


def _beneficiary_scope_q(user, *, programme_partner_field: str,
                          household_sub_region_field: str) -> Q:
    """Combined ABAC: union of partner scope OR geographic scope.

    A partner analyst sees their partner's programmes; a CDO
    scoped to a sub-region sees that sub-region's households; an
    operator with both scopes sees the union. National / superuser
    bypass entirely.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    if getattr(user, "is_superuser", False):
        return ~Q(pk__in=[])

    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", "scope_code"),
    )
    if not scopes:
        return Q(pk__in=[])
    if any(level == ScopeLevel.NATIONAL for level, _ in scopes):
        return ~Q(pk__in=[])

    partner_codes = [c for level, c in scopes if level == ScopeLevel.PARTNER and c]
    sub_region_codes = [c for level, c in scopes if level == ScopeLevel.SUB_REGION and c]

    q = Q()
    if partner_codes:
        partner_ids = list(
            Partner.objects.filter(code__in=partner_codes).values_list("id", flat=True),
        )
        q |= Q(**{f"{programme_partner_field}__in": partner_ids})
    if sub_region_codes:
        q |= Q(**{f"{household_sub_region_field}__in": sub_region_codes})

    if not q:
        return Q(pk__in=[])
    return q


def _months_between(start: date | None, end: date) -> int:
    if start is None:
        return 0
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def _enrolment_to_row(enr: ProgrammeEnrolment, today: date) -> dict:
    prog = enr.programme
    hh = enr.household
    pmd = enr.payment_metadata or {}
    referral = enr.referral

    # Derived months_in from enrolled_at (Referral.enrolled_at if a
    # referral originated the enrolment) or effective_date.
    enrolled_dt = (
        referral.enrolled_at.date()
        if referral and referral.enrolled_at
        else enr.effective_date
    )
    months_in = _months_between(enrolled_dt, today)

    # Exit projection — for an exited enrolment we surface the exit
    # code mapped via the programme_exit_reason ChoiceList. The model
    # stores the human-readable reason in exit_reason; numeric exit
    # codes land via payment_metadata.exit_code if set by the partner.
    exit_code = pmd.get("exit_code")
    exit_at = (referral.exited_at.date() if referral and referral.exited_at else None) \
        if enr.status == "exited" else None
    suspend_reason = pmd.get("suspend_reason") if enr.status == "suspended" else None
    suspend_at = pmd.get("suspend_at") if enr.status == "suspended" else None

    head = hh.head_member
    head_name = (
        f"{head.surname} {head.first_name}".strip()
        if head else ""
    )

    return {
        "id": str(enr.id),
        "household_id": str(hh.id),
        "household_head_name": head_name,
        "household_sex": (head.sex if head else ""),
        "household_size": hh.members.count(),
        "district":        hh.district.name if hh.district_id else "",
        "parish":          hh.parish.name if hh.parish_id else "",
        "sub_region_code": hh.sub_region.code if hh.sub_region_id else "",
        "sub_region_name": hh.sub_region.name if hh.sub_region_id else "",

        "programme_id":          str(prog.id),
        "programme_code":        prog.code or "",
        "programme_name":        prog.name,
        "programme_kind":        prog.kind or "",
        "programme_kind_label":  resolve_label("programme_kind", prog.kind or ""),
        "unit_of_enrolment":     prog.unit_of_enrolment or "",
        "unit_of_enrolment_label": resolve_label(
            "programme_unit_of_enrolment", prog.unit_of_enrolment or "",
        ),
        "channel":               prog.channel or "",
        "cohort":                pmd.get("cohort", ""),

        "status":       enr.status,
        "status_label": resolve_label("programme_enrolment_status", enr.status),

        "enrolled_at":  enrolled_dt.isoformat() if enrolled_dt else None,
        "months_in":    months_in,
        "effective_date": enr.effective_date.isoformat() if enr.effective_date else None,

        "last_pay_at":  pmd.get("last_pay_at"),
        "last_pay_amt": pmd.get("last_pay_amt", 0),
        "total_paid":   pmd.get("total_paid", 0),
        "next_pay_at":  pmd.get("next_pay_at"),

        "exited_at":      exit_at.isoformat() if exit_at else None,
        "exit_code":      exit_code,
        "exit_code_label": (
            resolve_label("programme_exit_reason", exit_code)
            if exit_code else None
        ),
        "exit_note":      enr.exit_reason or None,

        "suspend_reason": suspend_reason,
        "suspend_at":     suspend_at,

        "pmt_score": float(hh.current_pmt_score) if hh.current_pmt_score is not None else None,
        "note":      pmd.get("note", ""),
    }


def _pending_referral_to_row(ref: Referral, today: date) -> dict:
    prog = ref.programme
    hh = ref.household
    head = hh.head_member
    head_name = (
        f"{head.surname} {head.first_name}".strip()
        if head else ""
    )
    return {
        "id": str(ref.id),
        "household_id": str(hh.id),
        "household_head_name": head_name,
        "household_sex": (head.sex if head else ""),
        "household_size": hh.members.count(),
        "district":        hh.district.name if hh.district_id else "",
        "parish":          hh.parish.name if hh.parish_id else "",
        "sub_region_code": hh.sub_region.code if hh.sub_region_id else "",
        "sub_region_name": hh.sub_region.name if hh.sub_region_id else "",

        "programme_id":          str(prog.id),
        "programme_code":        prog.code or "",
        "programme_name":        prog.name,
        "programme_kind":        prog.kind or "",
        "programme_kind_label":  resolve_label("programme_kind", prog.kind or ""),
        "unit_of_enrolment":     prog.unit_of_enrolment or "",
        "unit_of_enrolment_label": resolve_label(
            "programme_unit_of_enrolment", prog.unit_of_enrolment or "",
        ),
        "channel":               prog.channel or "",
        "cohort":                "",

        # Derived state per ADR-0015 §"Decision 4".
        "status":       "pending",
        "status_label": resolve_label("programme_enrolment_status", "pending"),

        "enrolled_at":    None,
        "months_in":      0,
        "effective_date": None,

        "last_pay_at":  None,
        "last_pay_amt": 0,
        "total_paid":   0,
        "next_pay_at":  None,

        "exited_at":      None,
        "exit_code":      None,
        "exit_code_label": None,
        "exit_note":      None,

        "suspend_reason": None,
        "suspend_at":     None,

        "pmt_score": float(hh.current_pmt_score) if hh.current_pmt_score is not None else None,
        "note":      ref.reason or "",
    }


def _enrolment_queryset(request):
    qs = ProgrammeEnrolment.objects.select_related(
        "programme", "programme__partner",
        "household", "household__sub_region",
        "household__district", "household__parish",
        "household__head_member",
        "referral",
    )
    qs = qs.filter(_beneficiary_scope_q(
        request.user,
        programme_partner_field="programme__partner_id",
        household_sub_region_field="household__sub_region_code",
    ))
    return qs


def _pending_referral_queryset(request):
    """Referrals in sent/accepted with no enrolment row yet."""
    qs = Referral.objects.select_related(
        "programme", "programme__partner",
        "household", "household__sub_region",
        "household__district", "household__parish",
        "household__head_member",
    ).filter(status__in=("sent", "accepted")).filter(enrolments__isnull=True)
    qs = qs.filter(_beneficiary_scope_q(
        request.user,
        programme_partner_field="programme__partner_id",
        household_sub_region_field="household__sub_region_code",
    ))
    return qs


class _BeneficiaryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


@extend_schema(
    tags=["beneficiaries"],
    summary="Per-programme enrolment ledger (US-S26-006)",
    description=(
        "One row per (household, programme). Status is the persisted "
        "ProgrammeEnrolment status, or the derived 'pending' state "
        "for Referrals still in flight (sent/accepted) with no "
        "enrolment yet. ABAC-scoped: partner-affiliated users see "
        "their partner's programmes only; geographic operators see "
        "their sub-regions; national/superuser see all."
    ),
    parameters=[
        OpenApiParameter("programme",  OpenApiTypes.STR, required=False,
                         description="Filter by Programme.id."),
        OpenApiParameter("programme_code", OpenApiTypes.STR, required=False,
                         description="Filter by Programme.code (string)."),
        OpenApiParameter("status",     OpenApiTypes.STR, required=False,
                         description="active | suspended | pending | exited."),
        OpenApiParameter("sub_region", OpenApiTypes.STR, required=False,
                         description="GeographicUnit.code at sub_region level."),
        OpenApiParameter("exit_code",  OpenApiTypes.STR, required=False,
                         description="Filter exited rows by exit-reason code."),
        OpenApiParameter("kind",       OpenApiTypes.STR, required=False,
                         description="Filter by Programme.kind (cash_transfer, ...)."),
        OpenApiParameter("q",          OpenApiTypes.STR, required=False,
                         description="Search head name, household id, parish, district."),
        OpenApiParameter("page",       OpenApiTypes.INT, required=False),
        OpenApiParameter("page_size",  OpenApiTypes.INT, required=False),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def beneficiaries_list(request):
    today = date.today()
    params = request.query_params

    # ---- Filter primitives applied to both source querysets ----
    def _apply_common_filters(qs):
        programme = params.get("programme")
        if programme:
            qs = qs.filter(programme_id=programme)
        programme_code = params.get("programme_code")
        if programme_code:
            qs = qs.filter(programme__code=programme_code)
        sub_region = params.get("sub_region")
        if sub_region:
            qs = qs.filter(household__sub_region_code=sub_region)
        kind = params.get("kind")
        if kind:
            qs = qs.filter(programme__kind=kind)
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(household_id__icontains=q)
                | Q(household__head_member__surname__icontains=q)
                | Q(household__head_member__first_name__icontains=q)
                | Q(household__parish__name__icontains=q)
                | Q(household__district__name__icontains=q),
            )
        return qs

    status_filter = params.get("status")
    exit_code_filter = params.get("exit_code")

    enrolments = _apply_common_filters(_enrolment_queryset(request))
    if status_filter:
        # Status filter applies to the persisted enrolment status only;
        # 'pending' is the derived state below.
        enrolments = enrolments.filter(status=status_filter)
    if exit_code_filter:
        enrolments = enrolments.filter(
            status="exited",
            payment_metadata__exit_code=exit_code_filter,
        )

    rows: list[dict] = []
    if status_filter != "pending":
        # Only walk enrolments when the caller isn't restricted to pending.
        for enr in enrolments.order_by("-effective_date", "id"):
            rows.append(_enrolment_to_row(enr, today))

    # Pending = referral-only rows. Skip when caller filtered to a
    # persisted enrolment status, or when an exit_code filter is set.
    if status_filter in (None, "", "pending") and not exit_code_filter:
        pending = _apply_common_filters(_pending_referral_queryset(request))
        for ref in pending.order_by("-sent_at", "id"):
            rows.append(_pending_referral_to_row(ref, today))

    # Pagination (manual — DRF pagination wraps a queryset, not a list).
    paginator = _BeneficiaryPagination()
    page = paginator.paginate_queryset(rows, request, view=None)
    return paginator.get_paginated_response(page)
