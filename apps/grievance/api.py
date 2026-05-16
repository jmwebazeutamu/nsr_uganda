from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.abac import HouseholdIdScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

from .models import Grievance, GrievanceStatus
from .services import GrievanceError, assign, close, escalate, open_grievance, resolve


class GrievanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grievance
        fields = (
            "id", "category", "sub_category", "description",
            "household_id", "member_id",
            "reporter_name", "reporter_phone", "reporter_relationship",
            "tier", "status", "assigned_to",
            "opened_at", "sla_deadline", "resolved_at", "closed_at",
            "resolution_narrative", "linked_change_request_id",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "status", "opened_at", "sla_deadline",
            "resolved_at", "closed_at", "created_at", "updated_at",
        )


class _ActorReason(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True)


class _Assign(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    assigned_to = serializers.CharField(max_length=64)


class _Resolve(serializers.Serializer):
    actor = serializers.CharField(max_length=64)
    narrative = serializers.CharField()
    linked_change_request_id = serializers.CharField(required=False, allow_blank=True)


@extend_schema_view(
    list=extend_schema(tags=["grm"], summary="List grievances"),
    retrieve=extend_schema(tags=["grm"], summary="Retrieve a grievance"),
    create=extend_schema(tags=["grm"], summary="Open a new grievance"),
)
class GrievanceViewSet(
    AuditReadMixin, HouseholdIdScopedQuerysetMixin, viewsets.ModelViewSet,
):
    audit_entity_type = "grievance"
    # Grievance.household_id is a CharField (not a real FK) because the
    # GRM may open before a confirmed household exists.
    scope_field_path = "household_id"
    queryset = Grievance.objects.all().order_by("-opened_at")
    serializer_class = GrievanceSerializer
    filterset_fields = ["status", "tier", "category", "assigned_to",
                        "household_id"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = open_grievance(
                category=ser.validated_data["category"],
                description=ser.validated_data["description"],
                household_id=ser.validated_data.get("household_id", ""),
                member_id=ser.validated_data.get("member_id", ""),
                reporter_name=ser.validated_data.get("reporter_name", ""),
                reporter_phone=ser.validated_data.get("reporter_phone", ""),
                reporter_relationship=ser.validated_data.get("reporter_relationship", ""),
                tier=ser.validated_data.get("tier") or "l1_parish_chief",
                assigned_to=ser.validated_data.get("assigned_to", ""),
                sub_category=ser.validated_data.get("sub_category", ""),
                actor=request.user.username or "anonymous",
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["grm"], summary="Assign a grievance", request=_Assign,
                   responses={200: GrievanceSerializer})
    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        ser = _Assign(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = assign(self.get_object(), assigned_to=ser.validated_data["assigned_to"],
                       actor=ser.validated_data["actor"])
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(tags=["grm"], summary="Escalate a grievance", request=_ActorReason,
                   responses={200: GrievanceSerializer})
    @action(detail=True, methods=["post"], url_path="escalate")
    def escalate(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = escalate(self.get_object(), actor=ser.validated_data["actor"],
                         reason=ser.validated_data.get("reason", ""))
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(tags=["grm"], summary="Resolve a grievance", request=_Resolve,
                   responses={200: GrievanceSerializer})
    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, pk=None):
        ser = _Resolve(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = resolve(
                self.get_object(),
                actor=ser.validated_data["actor"],
                narrative=ser.validated_data["narrative"],
                linked_change_request_id=ser.validated_data.get("linked_change_request_id", ""),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(tags=["grm"], summary="Close a resolved grievance", request=_ActorReason,
                   responses={200: GrievanceSerializer,
                              400: OpenApiResponse(description="not RESOLVED")})
    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        ser = _ActorReason(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = close(self.get_object(), actor=ser.validated_data["actor"])
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(
        tags=["grm"],
        summary="List grievances past their SLA deadline",
        description=("Returns open / in-progress / escalated grievances whose "
                     "sla_deadline is in the past. The queryset is ABAC-scoped "
                     "via the same HouseholdIdScopedQuerysetMixin path as the "
                     "main list — a sub-region operator only sees overdue "
                     "items they have authority over. Powers L2/L3/L4 "
                     "supervision dashboards."),
        responses={200: GrievanceSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="overdue")
    def overdue(self, request):
        from django.utils import timezone
        qs = self.filter_queryset(self.get_queryset()).filter(
            sla_deadline__lt=timezone.now(),
            status__in=[GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS,
                        GrievanceStatus.ESCALATED],
        ).order_by("sla_deadline")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(qs, many=True).data)
