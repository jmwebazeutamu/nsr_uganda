from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.audit_views import AuditReadMixin

from .models import Grievance, GrievanceStatus, GrievanceTask, TaskStatus
from .services import (
    GrievanceError,
    assign,
    close,
    create_task,
    escalate,
    open_grievance,
    resolve,
    transition_task,
)

GRM_OFFICER_GROUP = "GRM Officer"


def _is_grm_officer(user) -> bool:
    """True if the user is a superuser OR belongs to the GRM Officer
    Django group. GRM Officers see every grievance + every task,
    regardless of who they're assigned to."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name=GRM_OFFICER_GROUP).exists()


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
class GrievanceViewSet(AuditReadMixin, viewsets.ModelViewSet):
    audit_entity_type = "grievance"
    queryset = Grievance.objects.all().order_by("-opened_at")
    serializer_class = GrievanceSerializer
    filterset_fields = ["status", "tier", "category", "assigned_to",
                        "household_id"]

    def get_queryset(self):
        """US-S21-003b — role-based visibility:

        - GRM Officer (group) and superusers see every grievance.
        - Every other authenticated user sees only grievances they
          OWN — either Grievance.assigned_to == their username, OR
          they hold a non-closed GrievanceTask on the grievance.
        - Anonymous users see nothing.

        Replaces the prior HouseholdIdScopedQuerysetMixin behaviour;
        geographic scoping for grievances was a stand-in for the
        actual user model the project hadn't decided on. With the
        GRM Officer role explicit we no longer need to fall back to
        geo.
        """
        from django.db.models import Q

        qs = super().get_queryset()
        user = self.request.user
        if _is_grm_officer(user):
            pass  # full visibility
        elif getattr(user, "is_authenticated", False):
            uname = user.username or ""
            qs = qs.filter(
                Q(assigned_to=uname)
                | Q(tasks__assigned_to=uname,
                    tasks__status__in=[
                        TaskStatus.OPEN, TaskStatus.IN_PROGRESS,
                    ]),
            ).distinct()
        else:
            qs = qs.none()

        # US-S15-003 — optional ?sub_region_code= drill-down for the
        # home queue panel. household_id is a CharField on Grievance,
        # so join through Household by IN-subquery.
        sr = self.request.query_params.get("sub_region_code")
        if sr:
            from apps.data_management.models import Household
            hh_ids = list(
                Household.objects.filter(sub_region_code=sr)
                                  .values_list("id", flat=True),
            )
            qs = qs.filter(household_id__in=hh_ids)
        return qs
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


# --- US-S21-003 — GrievanceTask API ---------------------------------------

class GrievanceTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrievanceTask
        fields = (
            "id", "grievance", "title", "description",
            "assigned_to", "status",
            "created_by", "created_at", "updated_at",
            "closed_at", "closed_by",
        )
        read_only_fields = (
            "id", "status", "created_by", "created_at", "updated_at",
            "closed_at", "closed_by",
        )


class _TaskCreate(serializers.Serializer):
    grievance = serializers.CharField(max_length=26)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    assigned_to = serializers.CharField(max_length=64)


class _TaskTransition(serializers.Serializer):
    new_status = serializers.ChoiceField(choices=TaskStatus.choices)


@extend_schema_view(
    list=extend_schema(tags=["grm"], summary="List grievance tasks"),
    retrieve=extend_schema(tags=["grm"], summary="Retrieve a task"),
    create=extend_schema(tags=["grm"], summary="Create a task on a grievance"),
)
class GrievanceTaskViewSet(viewsets.ModelViewSet):
    """REST surface for GrievanceTask. Visibility mirrors Grievance:
    GRM Officers see every task; other operators see only tasks
    assigned to them (or tasks on grievances they own)."""

    queryset = GrievanceTask.objects.all().order_by("-created_at")
    serializer_class = GrievanceTaskSerializer
    filterset_fields = ["status", "grievance", "assigned_to"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        from django.db.models import Q
        qs = super().get_queryset()
        user = self.request.user
        if _is_grm_officer(user):
            return qs
        if not getattr(user, "is_authenticated", False):
            return qs.none()
        uname = user.username or ""
        # Visible iff assigned to me OR on a grievance I'm
        # assigned to (so the case lead sees every task they
        # delegated, not just their own).
        return qs.filter(
            Q(assigned_to=uname)
            | Q(grievance__assigned_to=uname),
        ).distinct()

    def create(self, request, *args, **kwargs):
        # Only GRM Officers can create tasks; regular users execute
        # what's assigned to them but can't scope new work onto a
        # grievance.
        if not _is_grm_officer(request.user):
            return Response(
                {"detail": "only GRM Officers can create tasks"},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = _TaskCreate(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            grievance = Grievance.objects.get(pk=ser.validated_data["grievance"])
        except Grievance.DoesNotExist:
            return Response(
                {"detail": "grievance not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            task = create_task(
                grievance,
                title=ser.validated_data["title"],
                description=ser.validated_data.get("description", ""),
                assigned_to=ser.validated_data["assigned_to"],
                actor=request.user.username or "admin",
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            self.get_serializer(task).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["grm"], summary="Transition a task's status",
                   request=_TaskTransition,
                   responses={200: GrievanceTaskSerializer})
    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        # Only the assignee OR a GRM Officer may transition a task.
        # An L1 chief can't close work scoped onto another operator.
        task = self.get_object()
        user = request.user
        uname = user.username or ""
        if not _is_grm_officer(user) and task.assigned_to != uname:
            return Response(
                {"detail": "only the assignee or a GRM Officer may transition"},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = _TaskTransition(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            task = transition_task(
                task,
                new_status=ser.validated_data["new_status"],
                actor=user.username or "admin",
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(task).data)
