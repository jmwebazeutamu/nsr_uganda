from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.actor import actor_from_request
from apps.security.audit_views import AuditReadMixin

from .models import (
    Grievance,
    GrievanceComment,
    GrievanceStatus,
    GrievanceTask,
    TaskStatus,
)
from .services import (
    GrievanceError,
    add_comment,
    assign,
    close,
    create_task,
    escalate,
    open_change_request_for_grievance,
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
            "opened_at", "sla_deadline",
            "resolved_at", "resolved_by", "resolution_narrative",
            "closed_at", "closed_by", "closing_narrative",
            "linked_change_request_id",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "status", "opened_at", "sla_deadline",
            "resolved_at", "resolved_by", "closed_at", "closed_by",
            "closing_narrative", "created_at", "updated_at",
        )


class _ActorReason(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    reason = serializers.CharField(required=False, allow_blank=True)


class _Assign(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    assigned_to = serializers.CharField(max_length=64)


class _Resolve(serializers.Serializer):
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    narrative = serializers.CharField()
    linked_change_request_id = serializers.CharField(required=False, allow_blank=True)


class GrievanceCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrievanceComment
        fields = ("id", "grievance", "task", "kind", "body", "author",
                  "created_at")
        read_only_fields = fields


class _CommentCreate(serializers.Serializer):
    body = serializers.CharField()


class _OpenChangeRequest(serializers.Serializer):
    """Open a UPD ChangeRequest from a DATA_CORRECTION grievance.

    `changes` is the UPD field-change map: {field: {old, new}}. It may
    be empty — the reviewer often knows a correction is needed before
    knowing exactly what it should say, and the Updates Queue is where
    that gets filled in.
    """
    changes = serializers.JSONField(required=False)
    auto_submit = serializers.BooleanField(required=False, default=False)


class _Close(serializers.Serializer):
    """US-S21-005 — close grievance with a captured narrative.
    `narrative` is the reason + note pair the closing operator gave;
    persisted on Grievance.closing_narrative."""
    actor = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Ignored - the acting user comes from the authenticated session.",
    )
    narrative = serializers.CharField(required=False, allow_blank=True)


@extend_schema_view(
    list=extend_schema(tags=["grm"], summary="List grievances"),
    retrieve=extend_schema(tags=["grm"], summary="Retrieve a grievance"),
    create=extend_schema(tags=["grm"], summary="Open a new grievance"),
)
class GrievanceViewSet(AuditReadMixin, viewsets.ModelViewSet):
    # Grievance handling contacts the citizen about their case.
    # Vocabulary is the ConsentPurpose catalogue (DEP-22), not a
    # second list of purposes beside the consent one.
    access_purpose = "GRIEVANCE_CONTACT"
    audit_entity_type = "grievance"
    queryset = Grievance.objects.all().order_by("-opened_at")
    serializer_class = GrievanceSerializer

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

        US-S21-004 — query-param filters are applied manually because
        django-filter isn't installed; declaring filterset_fields
        alone was silently a no-op. Supported: status, tier, category,
        assigned_to, household_id (+ sub_region_code drill-down).
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

        # Apply per-field query-param filters. Each is opt-in — empty
        # string or missing leaves the queryset alone.
        for field in ("status", "tier", "category",
                      "assigned_to", "household_id"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})

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
                       actor=actor_from_request(request))
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
            g = escalate(self.get_object(), actor=actor_from_request(request),
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
                actor=actor_from_request(request),
                narrative=ser.validated_data["narrative"],
                linked_change_request_id=ser.validated_data.get("linked_change_request_id", ""),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(tags=["grm"], summary="Close a resolved grievance", request=_Close,
                   responses={200: GrievanceSerializer,
                              400: OpenApiResponse(description="not RESOLVED")})
    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        ser = _Close(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            g = close(
                self.get_object(),
                actor=actor_from_request(request),
                narrative=ser.validated_data.get("narrative", ""),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(g).data)

    @extend_schema(
        tags=["grm"],
        summary="The grievance's running comment thread",
        description=(
            "A grievance used to carry no running record: the intake "
            "narrative, then the resolution. The weeks between had "
            "nowhere to go. GET lists the thread oldest-first; POST "
            "appends. Comments are append-only — a correction is "
            "another comment."
        ),
        responses={200: GrievanceCommentSerializer(many=True)},
    )
    @action(detail=True, methods=["get", "post"], url_path="comments")
    def comments(self, request, pk=None):
        grievance = self.get_object()
        if request.method == "GET":
            rows = grievance.comments.all().select_related("task")
            return Response(GrievanceCommentSerializer(rows, many=True).data)

        ser = _CommentCreate(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            comment = add_comment(
                grievance,
                body=ser.validated_data["body"],
                actor=actor_from_request(request),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(GrievanceCommentSerializer(comment).data,
                        status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["grm"],
        summary="Open a linked UPD ChangeRequest",
        description=(
            "SAD §4.4: a grievance that resolves to a data correction "
            "opens a linked UPD. The service has done this since "
            "US-S21; nothing exposed it, so the Updates Queue and the "
            "grievance that caused the update were two screens with no "
            "path between them. Returns the grievance with "
            "`linked_change_request_id` populated."
        ),
        request=_OpenChangeRequest,
        responses={200: GrievanceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="open-change-request")
    def open_change_request(self, request, pk=None):
        if not _is_grm_officer(request.user):
            return Response(
                {"detail": "GRM Officer role required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = _OpenChangeRequest(data=request.data)
        ser.is_valid(raise_exception=True)
        grievance = self.get_object()
        try:
            open_change_request_for_grievance(
                grievance,
                requester=actor_from_request(request),
                changes=ser.validated_data.get("changes") or {},
                auto_submit=ser.validated_data.get("auto_submit", False),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        grievance.refresh_from_db()
        return Response(self.get_serializer(grievance).data)

    @extend_schema(
        tags=["grm"],
        summary="Return the current user's GRM role + username",
        description=("Lets the React console show or hide the 'Add task' / "
                     "'Open grievance' affordances without a probe POST. "
                     "Returns {username, is_officer}."),
    )
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        return Response({
            "username": getattr(request.user, "username", "") or "",
            "is_officer": _is_grm_officer(request.user),
        })

    @extend_schema(
        tags=["grm"],
        summary="List grievances past their SLA deadline",
        description=("Returns open / in-progress / escalated grievances whose "
                     "sla_deadline is in the past. The queryset is role-scoped "
                     "via the same get_queryset path as the main list — a "
                     "non-officer only sees overdue items they own or hold "
                     "a task on. Powers L2/L3/L4 supervision dashboards."),
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
    # Required when closing. The service enforces it; declaring it
    # optional here lets re-open / start transitions stay one field.
    note = serializers.CharField(required=False, allow_blank=True)


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
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        """Visibility + query-param filters. django-filter isn't
        installed so filterset_fields was a silent no-op — we apply
        ?grievance=, ?status=, ?assigned_to= manually here."""
        from django.db.models import Q
        qs = super().get_queryset()
        user = self.request.user
        if _is_grm_officer(user):
            pass  # full visibility before filters
        elif not getattr(user, "is_authenticated", False):
            return qs.none()
        else:
            uname = user.username or ""
            # Visible iff assigned to me OR on a grievance I'm
            # assigned to (so the case lead sees every task they
            # delegated, not just their own).
            qs = qs.filter(
                Q(assigned_to=uname) | Q(grievance__assigned_to=uname),
            ).distinct()
        for field in ("status", "grievance", "assigned_to"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs

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
                note=ser.validated_data.get("note", ""),
            )
        except GrievanceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(task).data)
