"""DRF API for the partners module — US-S23-008.

Endpoints in this commit:

  GET    /api/v1/partners/                    list, with q/type/status/sector filters
  POST   /api/v1/partners/                    create (gated by PARTNERS_MODULE_ENABLED)
  GET    /api/v1/partners/{id}/               retrieve
  PATCH  /api/v1/partners/{id}/               update (gated)

Dashboard + DSA + signature endpoints land in US-S23-009 / 010.

Per ADR-0010, every coded field on the response carries both the
raw `<field>` and the resolved `<field>_label` companion (auto-
attached via apps.data_management.serializer_labels).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Sum
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.data_management.serializer_labels import attach_label_methodfields
from apps.security.abac import PartnerScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .choice_field_map import MODEL_FIELDS
from .models import (
    DataSharingAgreement,
    DsaSignature,
    Partner,
    PartnerUsageDaily,
    Programme,
)
from .services import scope as scope_service
from .services import signature as signature_service
from .services.activity import for_partner as activity_for_partner


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = (
            "id", "code", "name", "registration_no", "country", "website",
            "primary_email",
            # Coded fields and their resolved labels (attached below).
            "type", "type_label",
            "sector", "sector_label",
            "status", "status_label",
            "tone", "tone_label",
            "lead_user", "logo_short", "note",
            "last_activity_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "created_at", "updated_at", "last_activity_at",
        )


attach_label_methodfields(PartnerSerializer, MODEL_FIELDS["Partner"])


class _PartnersWriteFlagPermission(permissions.BasePermission):
    """Read endpoints are open to any authenticated caller; write
    endpoints respect the PARTNERS_MODULE_ENABLED feature flag.
    Refuses with 403 when the flag is off."""

    message = "Partners module is gated off (PARTNERS_MODULE_ENABLED)."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not getattr(settings, "PARTNERS_MODULE_ENABLED", False):
            raise PermissionDenied(self.message)
        return True


@extend_schema_view(
    list=extend_schema(
        tags=["partners"], summary="List partners",
        description="Filters: q (search name/code), type, status, sector.",
    ),
    retrieve=extend_schema(tags=["partners"], summary="Retrieve a partner"),
    create=extend_schema(tags=["partners"], summary="Create a partner"),
    partial_update=extend_schema(tags=["partners"], summary="Update a partner"),
)
class PartnerViewSet(AuditReadMixin, PartnerScopedQuerysetMixin,
                     viewsets.ModelViewSet):
    """CRUD for partner organisations. Writes are flag-gated.
    Per ADR-0013 ABAC: partner-affiliated users see only their own
    Partner; NSR Unit / national / superuser see all."""

    audit_entity_type = "partner"
    partner_id_field = "id"
    queryset = Partner.objects.all().order_by("-last_activity_at", "code")
    serializer_class = PartnerSerializer
    permission_classes = [permissions.IsAuthenticated, _PartnersWriteFlagPermission]
    # Disable PUT — the spec only authorises PATCH (partial update).
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        for key in ("type", "status", "sector"):
            v = params.get(key)
            if v:
                qs = qs.filter(**{key: v})
        return qs


# --- Dashboard aggregation endpoints (US-S23-009) ---------------------------
#
# These read against Partner + DataSharingAgreement + PartnerUsageDaily and
# return shapes the JSX dashboard widgets consume directly. Each endpoint
# is intentionally a single SQL aggregation; the dashboard refreshes them
# on a polling interval so we keep query cost cheap.


def _rolling_window(days: int = 30) -> tuple[date, date]:
    """Return (start_date, today) — inclusive of today."""
    today = date.today()
    return today - timedelta(days=days - 1), today


@extend_schema(
    tags=["partners"],
    summary="Partner-registry KPIs (US-S23-009)",
    description=(
        "Counts that drive the four KPI cards on the partners "
        "dashboard: active partners, active DSAs, rows delivered "
        "in the trailing 30 days, and DSA budget breaches."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_summary(request):
    start, end = _rolling_window(30)

    # Active partners: anything that is currently delivering (active,
    # renewing, alert) or under contract (onboarding/provider counts
    # are surfaced separately in the dashboard but not here).
    active_partners = Partner.objects.filter(
        status__in=("active", "renewing", "alert"),
    ).count()

    onboarding_partners = Partner.objects.filter(status="onboarding").count()

    active_dsas = DataSharingAgreement.objects.filter(
        status="active",
    ).count()

    expiring_30 = DataSharingAgreement.objects.filter(
        status__in=("active", "expiring"),
        effective_to__isnull=False,
        effective_to__lte=date.today() + timedelta(days=30),
        effective_to__gte=date.today(),
    ).count()

    usage = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end)
        .aggregate(total=Sum("rows_delivered"))
    )
    rows_30d = usage["total"] or 0

    # Distinct partners that delivered any rows in the window.
    active_requesters = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end, rows_delivered__gt=0)
        .values("partner").distinct().count()
    )

    # Budget breaches — partners whose 30d sum exceeds their DSA budget.
    # Only DSAs with a non-null monthly_row_budget count (providers skip).
    over_budget = 0
    for partner in Partner.objects.exclude(status="provider"):
        budget_total = (
            DataSharingAgreement.objects
            .filter(partner=partner, status="active",
                    monthly_row_budget__isnull=False)
            .aggregate(b=Sum("monthly_row_budget"))["b"] or 0
        )
        if budget_total <= 0:
            continue
        used = (
            PartnerUsageDaily.objects
            .filter(partner=partner, day__gte=start, day__lte=end)
            .aggregate(u=Sum("rows_delivered"))["u"] or 0
        )
        if used > budget_total:
            over_budget += 1

    return Response({
        "active_partners": active_partners,
        "onboarding_partners": onboarding_partners,
        "active_dsas": active_dsas,
        "dsas_expiring_30d": expiring_30,
        "rows_delivered_30d": rows_30d,
        "active_requesters_30d": active_requesters,
        "dsas_over_budget_30d": over_budget,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    })


@extend_schema(
    tags=["partners"],
    summary="DSAs by days-until-expiry (US-S23-009 / RenewalTimeline)",
    parameters=[
        OpenApiParameter(
            name="days", type=OpenApiTypes.INT, required=False,
            description="Window in days (default 120).",
        ),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_renewals(request):
    try:
        days = int(request.query_params.get("days") or 120)
    except ValueError:
        days = 120
    cutoff = date.today() + timedelta(days=days)
    qs = (
        DataSharingAgreement.objects
        .filter(
            effective_to__isnull=False,
            effective_to__gte=date.today(),
            effective_to__lte=cutoff,
        )
        .select_related("partner")
        .order_by("effective_to")
    )
    items = [
        {
            "dsa_id": d.id,
            "reference": d.reference,
            "partner_code": d.partner.code,
            "partner_name": d.partner.name,
            "partner_tone": d.partner.tone,
            "effective_to": d.effective_to.isoformat() if d.effective_to else None,
            "days_until_expiry": (d.effective_to - date.today()).days,
        }
        for d in qs
    ]
    return Response({"window_days": days, "items": items})


@extend_schema(
    tags=["partners"],
    summary="Partners-by-sector mix (US-S23-009 / SectorMix)",
    description=(
        "Returns one row per `partner_sector` code: partner count and "
        "trailing-30d rows delivered. Sectors with zero partners are "
        "omitted."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_sector_mix(request):
    start, end = _rolling_window(30)
    sectors = (
        Partner.objects.values("sector", "tone")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    out = []
    for row in sectors:
        sector_code = row["sector"] or ""
        if not sector_code:
            continue
        rows_delivered = (
            PartnerUsageDaily.objects
            .filter(partner__sector=sector_code,
                    day__gte=start, day__lte=end)
            .aggregate(s=Sum("rows_delivered"))["s"] or 0
        )
        out.append({
            "sector_code": sector_code,
            "tone": row["tone"] or "neutral",
            "partner_count": row["count"],
            "rows_delivered_30d": rows_delivered,
        })
    return Response({"items": out})


# --- Programme + DSA + Signature serializers (US-S23-010) -------------------


class ProgrammeSerializer(serializers.ModelSerializer):
    partner_code = serializers.CharField(source="partner.code", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    dsa_reference = serializers.CharField(
        source="dsa.reference", read_only=True, default="",
    )
    # Field-level defaults that mirror the model so the wizard can
    # POST sparse payloads (only `partner`, `name`, `kind` required).
    code = serializers.CharField(required=False, allow_blank=True, max_length=24)
    summary = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, max_length=32, default="draft")
    unit_of_enrolment = serializers.CharField(required=False, allow_blank=True, max_length=32)
    sex_filter = serializers.CharField(required=False, allow_blank=True, max_length=8)
    disbursement_cycle = serializers.CharField(required=False, allow_blank=True, max_length=32)
    channel = serializers.CharField(required=False, allow_blank=True, max_length=128)
    start_month = serializers.CharField(required=False, allow_blank=True, max_length=24)
    webhook_url = serializers.URLField(required=False, allow_blank=True)
    scope_text = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Programme
        fields = (
            "id", "partner", "partner_code", "partner_name",
            "code", "name", "summary",
            "kind", "kind_label",
            "status", "status_label",
            "dsa", "dsa_reference",
            # Cohort
            "unit_of_enrolment", "unit_of_enrolment_label",
            "cohort_target",
            "sex_filter", "sex_filter_label",
            "age_min", "age_max",
            "pmt_bands", "composition_flags",
            # Disbursement
            "amount_ugx",
            "disbursement_cycle", "disbursement_cycle_label",
            "duration_months", "channel", "start_month",
            # Geo
            "scope_text", "geographic_units", "beneficiary_estimate",
            # Lifecycle
            "exit_codes_allowed", "auto_exit_triggers",
            "suspend_on_grievance",
            # Webhook
            "webhook_url",
            # NB: webhook_secret_hash and start/end dates intentionally
            # omitted from the write surface — cleartext secret is
            # returned only by the create response, not on read.
            "start_date", "end_date",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "created_at", "updated_at",
            "partner_code", "partner_name", "dsa_reference",
        )
        # The (partner, code) UniqueConstraint marks both fields as
        # "required" through DRF's auto-generated UniqueTogetherValidator
        # — which conflicts with the wizard saving sparse drafts that
        # may not have a code yet. We drop the auto-validator and check
        # uniqueness manually in `validate()` only when code is non-empty.
        validators: list = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        partner = attrs.get("partner") or getattr(self.instance, "partner", None)
        code = (attrs.get("code") or "").strip()
        if partner and code:
            qs = Programme.objects.filter(partner=partner, code=code)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    "code": (
                        f"Programme code {code!r} already exists for "
                        f"partner {partner.code}."
                    ),
                })
        return attrs


attach_label_methodfields(ProgrammeSerializer, MODEL_FIELDS["Programme"])


class DsaSignatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = DsaSignature
        fields = (
            "id", "dsa", "sequence_order",
            "signer_role", "signer_role_label",
            "signer_name", "signer_email",
            "method", "method_label",
            "status", "status_label",
            "signed_at", "decline_reason",
            "docusign_envelope_id", "evidence_doc_ref",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "signed_at", "docusign_envelope_id",
            "created_at", "updated_at",
        )


attach_label_methodfields(DsaSignatureSerializer, MODEL_FIELDS["DsaSignature"])


class DsaSerializer(serializers.ModelSerializer):
    signatures = DsaSignatureSerializer(many=True, read_only=True)
    partner_code = serializers.CharField(source="partner.code", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    partner_tone = serializers.CharField(source="partner.tone", read_only=True)

    class Meta:
        model = DataSharingAgreement
        fields = (
            "id", "reference", "partner",
            "partner_code", "partner_name", "partner_tone",
            "programmes", "version",
            "status", "status_label",
            "effective_from", "effective_to", "monthly_row_budget",
            "entities_scope", "field_scope", "geographic_scope",
            "sensitive_data_handling", "sensitive_data_handling_label",
            "retention_days", "classification",
            "dpia_document_ref", "breach_sla_hours",
            "created_at", "signed_at", "updated_at",
            "signatures",
        )
        read_only_fields = (
            "id", "created_at", "signed_at", "updated_at",
            "version",
        )


attach_label_methodfields(
    DsaSerializer, MODEL_FIELDS["DataSharingAgreement"],
)


# --- DSA + signature viewsets ----------------------------------------------


@extend_schema_view(
    list=extend_schema(tags=["partners"], summary="List DSAs"),
    retrieve=extend_schema(tags=["partners"], summary="Retrieve a DSA"),
    create=extend_schema(tags=["partners"], summary="Create a draft DSA"),
    partial_update=extend_schema(tags=["partners"], summary="Update a DSA"),
)
class DsaViewSet(AuditReadMixin, PartnerScopedQuerysetMixin,
                 viewsets.ModelViewSet):
    """CRUD + submit-for-signoff + edit-scope actions on Data Sharing
    Agreements. ABAC-scoped by partner — see PartnerScopedQuerysetMixin."""

    audit_entity_type = "dsa"
    partner_id_field = "partner_id"
    queryset = (
        DataSharingAgreement.objects.all()
        .select_related("partner")
        .prefetch_related("signatures")
        .order_by("-created_at")
    )
    serializer_class = DsaSerializer
    permission_classes = [permissions.IsAuthenticated, _PartnersWriteFlagPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        partner = self.request.query_params.get("partner")
        if partner:
            qs = qs.filter(partner_id=partner)
        st = self.request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        return qs

    def partial_update(self, request, *args, **kwargs):
        # Per ADR-0016 §"Decision 2", an active DSA is a signed legal
        # instrument; its scope cannot change in place. Operators
        # must go through /edit-scope/ which clones to a fresh v+1
        # draft and forces the ADR-0012 sign-off chain.
        instance = self.get_object()
        if instance.status == "active":
            return Response(
                {
                    "detail": (
                        "Active DSAs cannot be patched in place. "
                        "POST to /api/v1/dsas/{id}/edit-scope/ to clone "
                        "to a draft v+1."
                    ),
                    "edit_scope_url": f"/api/v1/dsas/{instance.id}/edit-scope/",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        tags=["partners"],
        summary="Submit a DSA for the three-step sign-off chain",
        description=(
            "Implements ADR-0012's transition: status=draft → "
            "pending_signature, three DsaSignature rows created, "
            "first envelope dispatched. Requires partner_signer_email, "
            "nsr_unit_lead_email, dpo_email — all distinct."
        ),
    )
    @action(detail=True, methods=["post"], url_path="submit-for-signoff")
    def submit_for_signoff(self, request, pk=None):
        dsa = self.get_object()
        try:
            signature_service.submit_for_signoff(
                dsa,
                actor=str(request.user.username or request.user.id),
                partner_signer_email=request.data.get("partner_signer_email", ""),
                partner_signer_name=request.data.get("partner_signer_name", ""),
                nsr_unit_lead_email=request.data.get("nsr_unit_lead_email", ""),
                nsr_unit_lead_name=request.data.get("nsr_unit_lead_name", ""),
                dpo_email=request.data.get("dpo_email", ""),
                dpo_name=request.data.get("dpo_name", ""),
            )
        except signature_service.SignatureError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dsa.refresh_from_db()
        return Response(self.get_serializer(dsa).data)

    @extend_schema(
        tags=["partners"],
        summary="Edit a DSA's scope (ADR-0016)",
        description=(
            "Applies scope changes to a DSA. On a draft DSA the "
            "changes land in place. On an active DSA the row is "
            "cloned to a v+1 draft (the original is left untouched) "
            "and the caller is expected to dispatch the new draft "
            "through the ADR-0012 sign-off chain. Other statuses "
            "(pending_signature, expired, suspended, renewed) are "
            "rejected. Mutable fields: field_scope, entities_scope, "
            "monthly_row_budget, sensitive_data_handling, "
            "retention_days, classification, dpia_document_ref, "
            "breach_sla_hours, geographic_scope_ids."
        ),
    )
    @action(detail=True, methods=["post"], url_path="edit-scope")
    def edit_scope(self, request, pk=None):
        dsa = self.get_object()
        try:
            result = scope_service.edit_scope(
                dsa,
                actor=str(request.user.username or request.user.id),
                **{
                    k: v for k, v in request.data.items()
                    if k in {
                        "field_scope", "entities_scope",
                        "monthly_row_budget", "sensitive_data_handling",
                        "retention_days", "classification",
                        "dpia_document_ref", "breach_sla_hours",
                        "geographic_scope_ids",
                    }
                },
            )
        except scope_service.ScopeEditError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(result).data)

    @extend_schema(
        tags=["partners"],
        summary="Renew a DSA (ADR-0016)",
        description=(
            "Clones an active DSA into a v+1 draft, scope copied "
            "verbatim, signatures empty, effective_from/effective_to "
            "reset to NULL for the operator to fill in. Renewing a "
            "DSA whose status is already `renewed` silently redirects "
            "to the latest active version of the same reference "
            "(OI-S27-2). Other statuses (draft, pending_signature, "
            "expired, suspended) are rejected with 400. Supersession "
            "of the prior active version happens when the new draft "
            "reaches `status=active` (see record_signature)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="renew")
    def renew(self, request, pk=None):
        dsa = self.get_object()
        try:
            result = scope_service.renew(
                dsa,
                actor=str(request.user.username or request.user.id),
            )
        except scope_service.ScopeEditError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(result).data)


# --- Programme CRUD viewset (US-S25-003) ------------------------------------
#
# Nested-ish: the canonical write path is POST /api/v1/programmes/, and
# the partner-scoped lister at /api/v1/partners/{id}/programmes/ is a
# convenience that filters by parent partner. Both honour the ABAC
# partner scope so a UNICEF user cannot see OPM programmes.


@extend_schema_view(
    list=extend_schema(
        tags=["partners"], summary="List programmes",
        description=(
            "Filters: partner, status, kind, q (name/code icontains). "
            "ABAC-scoped per PartnerScopedQuerysetMixin."
        ),
    ),
    retrieve=extend_schema(tags=["partners"], summary="Retrieve a programme"),
    create=extend_schema(tags=["partners"], summary="Create a draft programme"),
    partial_update=extend_schema(tags=["partners"], summary="Update a programme"),
)
class ProgrammeViewSet(AuditReadMixin, PartnerScopedQuerysetMixin,
                       viewsets.ModelViewSet):
    """CRUD for partner-owned programmes. Same ABAC + write-flag gates
    as the Partner + DSA endpoints. Per US-S25-002 the model carries
    cohort / disbursement / lifecycle / webhook columns; the wizard
    submits a draft, the partner Data Steward signs off later (handled
    by a future signature workflow follow-up)."""

    audit_entity_type = "programme"
    partner_id_field = "partner_id"
    queryset = (
        Programme.objects.all()
        .select_related("partner", "dsa")
        .order_by("-created_at")
    )
    serializer_class = ProgrammeSerializer
    permission_classes = [permissions.IsAuthenticated, _PartnersWriteFlagPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        partner = params.get("partner")
        if partner:
            qs = qs.filter(partner_id=partner)
        st = params.get("status")
        if st:
            qs = qs.filter(status=st)
        kind = params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        return qs

    def perform_create(self, serializer):
        # Generate a webhook secret on draft creation so the wizard
        # can show it to the partner once. The cleartext lives only
        # in the in-memory response (set in `create()` below); only
        # sha256(secret) is persisted.
        import hashlib
        import secrets as _s
        cleartext = _s.token_urlsafe(32)
        digest = hashlib.sha256(cleartext.encode("utf-8")).hexdigest()
        prog = serializer.save(webhook_secret_hash=digest)
        # Audit the create.
        from apps.security.audit import emit as emit_audit
        emit_audit(
            "programme_created", "programme", prog.id,
            actor=str(self.request.user.username or self.request.user.id),
            reason=f"partner={prog.partner.code} code={prog.code}",
            field_changes={
                "partner_id": prog.partner_id,
                "partner_code": prog.partner.code,
                "code": prog.code,
                "kind": prog.kind,
                "cohort_target": prog.cohort_target,
            },
        )
        # Stash cleartext on the instance so create() picks it up.
        prog._cleartext_webhook_secret = cleartext

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        instance = serializer.instance
        data = self.get_serializer(instance).data
        # Surface the cleartext exactly once at create-time.
        secret = getattr(instance, "_cleartext_webhook_secret", "")
        if secret:
            data["webhook_secret_cleartext"] = secret
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["partners"],
    summary="List programmes for one partner (convenience for the detail screen)",
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partner_programmes(request, partner_id: str):
    rows = (
        Programme.objects.filter(partner_id=partner_id)
        .select_related("partner", "dsa")
        .order_by("-created_at")
    )
    data = ProgrammeSerializer(rows, many=True).data
    return Response({"items": data})


# --- Partner sub-resources (US-S23-010) -------------------------------------


@extend_schema(
    tags=["partners"],
    summary="Recent AuditEvent-derived activity for a partner",
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partner_activity(request, partner_id: str):
    events = activity_for_partner(partner_id, limit=50)
    return Response({"items": [e.as_dict() for e in events]})


@extend_schema(
    tags=["partners"],
    summary="Per-day usage for a partner (30 day window by default)",
    parameters=[
        OpenApiParameter(
            name="days", type=OpenApiTypes.INT, required=False,
            description="Window in days (default 30).",
        ),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partner_usage(request, partner_id: str):
    from datetime import date, timedelta
    try:
        days = max(1, int(request.query_params.get("days") or 30))
    except ValueError:
        days = 30
    start = date.today() - timedelta(days=days - 1)
    rows = (
        PartnerUsageDaily.objects
        .filter(partner_id=partner_id, day__gte=start)
        .order_by("day")
        .values("day", "rows_delivered", "requests_count")
    )
    return Response({
        "window_days": days,
        "items": [
            {
                "day": r["day"].isoformat(),
                "rows_delivered": r["rows_delivered"],
                "requests_count": r["requests_count"],
            }
            for r in rows
        ],
    })


@extend_schema(
    tags=["partners"],
    summary="Top N requesters by 30d row volume (US-S23-009)",
    parameters=[
        OpenApiParameter(
            name="n", type=OpenApiTypes.INT, required=False,
            description="Number of top requesters (default 5).",
        ),
    ],
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def partners_top_consumers(request):
    try:
        n = max(1, int(request.query_params.get("n") or 5))
    except ValueError:
        n = 5
    start, end = _rolling_window(30)
    rows = (
        PartnerUsageDaily.objects
        .filter(day__gte=start, day__lte=end, rows_delivered__gt=0)
        .values("partner", "partner__code", "partner__name", "partner__tone")
        .annotate(total=Sum("rows_delivered"))
        .order_by("-total")[:n]
    )
    items = [
        {
            "partner_id": r["partner"],
            "partner_code": r["partner__code"],
            "partner_name": r["partner__name"],
            "partner_tone": r["partner__tone"] or "neutral",
            "rows_delivered_30d": r["total"],
        }
        for r in rows
    ]
    return Response({"window_days": 30, "items": items})
