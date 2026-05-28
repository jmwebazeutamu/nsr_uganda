from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from .audit import emit as emit_audit
from .integrity import verify_audit_chain
from .models import AuditEvent, OperatorScope, ScopeLevel

# Group gating the OperatorScope management surface (US-S11-028).
# Tighter than IsDihTrigger because this controls who can see what
# personal data — security-sensitive enough to keep to System Admins.
_OPERATOR_SCOPE_ADMIN_GROUPS = ("nsr_admin",)


class IsOperatorScopeAdmin(permissions.BasePermission):
    """Gate the OperatorScope CRUD + user-search surface. Superusers
    always pass; otherwise membership in `nsr_admin` is required.
    Non-admin authenticated callers get 403 (not 404) so a misrouted
    operator notices."""

    message = (
        "OperatorScope administration requires membership in: "
        + ", ".join(_OPERATOR_SCOPE_ADMIN_GROUPS) + "."
    )

    def has_permission(self, request, view) -> bool:
        u = request.user
        if u is None or not getattr(u, "is_authenticated", False):
            return False
        if getattr(u, "is_superuser", False):
            return True
        return u.groups.filter(name__in=_OPERATOR_SCOPE_ADMIN_GROUPS).exists()


class AuditEventSerializer(serializers.ModelSerializer):
    prev_hash = serializers.SerializerMethodField()
    self_hash = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = (
            "id", "occurred_at", "actor_id", "actor_kind", "action",
            "entity_type", "entity_id", "field_changes", "reason",
            "ip_address", "user_agent", "prev_hash", "self_hash",
        )

    def get_prev_hash(self, obj) -> str | None:
        return obj.prev_hash.hex() if obj.prev_hash else None

    def get_self_hash(self, obj) -> str | None:
        return obj.self_hash.hex() if obj.self_hash else None


@extend_schema_view(
    list=extend_schema(tags=["security"], summary="List audit events"),
    retrieve=extend_schema(tags=["security"], summary="Retrieve an audit event"),
)
class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Append-only audit chain. SAD §8.4."""

    queryset = AuditEvent.objects.all().order_by("-occurred_at")
    serializer_class = AuditEventSerializer
    # entity_id added in US-S12-002 so the React household-detail
    # Audit tab can fetch a single entity's chain in one round-trip.
    filterset_fields = ["action", "entity_type", "actor_kind", "entity_id"]

    @extend_schema(
        tags=["security"],
        summary="Verify audit-chain integrity",
        request=None,
        responses={200: OpenApiResponse(description="chain verification report")},
    )
    @action(detail=False, methods=["post"], url_path="verify-chain")
    def verify_chain(self, request):
        raw_limit = request.data.get("limit") if isinstance(request.data, dict) else None
        try:
            limit = int(raw_limit) if raw_limit not in (None, "", "all") else None
        except (TypeError, ValueError):
            return Response({"detail": "limit must be an integer or omitted"},
                            status=status.HTTP_400_BAD_REQUEST)
        report = verify_audit_chain(limit=limit)
        return Response({
            "ok": report.ok,
            "mode": report.mode,
            "rows_scanned": report.rows_scanned,
            "breaks": [
                {
                    "event_id": b.event_id,
                    "occurred_at": b.occurred_at,
                    "expected_prev_hash": b.expected_prev_hash.hex() if b.expected_prev_hash else None,
                    "actual_prev_hash": b.actual_prev_hash.hex() if b.actual_prev_hash else None,
                }
                for b in report.breaks
            ],
        })


@extend_schema(
    tags=["security"],
    summary="Identity of the currently-authenticated user",
    description=(
        "Returns the request user's username, display name, role hint, "
        "and (if any) the partner organisation derived from their "
        "PARTNER-level OperatorScope. The topbar uses this so it can "
        "show 'opm-analyst · OPM' instead of falling back to the "
        "hardcoded persona fixture in screens-home.jsx."
    ),
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """GET /api/v1/security/users/me/ — identity of the current session."""
    u = request.user
    # Derive the role hint from scope + flags. Operator/NSR-unit covers
    # superusers and anyone with no PARTNER scope; partner-analyst is
    # anyone bound to a PARTNER-level OperatorScope.
    partner_codes = list(
        OperatorScope.objects.filter(
            user=u, active=True, scope_level=ScopeLevel.PARTNER,
        ).exclude(scope_code="").values_list("scope_code", flat=True),
    )
    role = "partner-analyst" if partner_codes else (
        "nsr-unit" if u.is_superuser else "operator"
    )
    partner_payload = None
    if partner_codes:
        # ADR-0013: canonical Partner lives in apps.partners. Resolve
        # the first active partner the user is bound to (multi-partner
        # accounts are out of MVP scope).
        from apps.partners.models import Partner
        p = Partner.objects.filter(code__in=partner_codes).first()
        if p is not None:
            partner_payload = {
                "id": str(p.id),
                "code": p.code,
                "name": p.name,
                "tone": p.tone or "neutral",
            }
    # US-S11-042 — when the session is impersonating, surface the
    # impersonator's identity so the topbar can render a banner.
    impersonator_payload = None
    impersonator_id = request.session.get("_impersonator_id")
    if impersonator_id is not None:
        from django.contrib.auth import get_user_model
        User = get_user_model()  # noqa: N806 — matches Django convention
        imp = User.objects.filter(id=impersonator_id).first()
        if imp is not None:
            impersonator_payload = {
                "id": imp.id,
                "username": imp.username,
                "display_name": imp.get_full_name() or imp.username,
                "reason": request.session.get("_impersonator_reason", ""),
            }

    # US-DATA-EXP-001: Data Explorer sidebar gate reads `roles` (list of
    # Keycloak realm-role codes) + `feature_flags.data_explorer_enabled`.
    # Roles surface from Django Groups for now; once Keycloak realm
    # roles sync (ADR-0006), this becomes a token-claim passthrough.
    roles = list(u.groups.values_list("name", flat=True))
    # Superusers implicitly hold every role so the dev/staging Tweaks
    # switcher works without a manual group assignment.
    if u.is_superuser and "EXPLORER" not in roles:
        roles.append("EXPLORER")
    feature_flags = {
        "data_explorer_enabled": bool(
            getattr(__import__("django.conf", fromlist=["settings"]).settings,
                    "DATA_EXPLORER_ENABLED", False),
        ),
    }

    return Response({
        "username": u.username,
        "display_name": (u.get_full_name() or u.username) if u.is_authenticated else "",
        "is_authenticated": True,
        "is_superuser": bool(u.is_superuser),
        "is_staff": bool(u.is_staff),
        "role": role,
        "roles": roles,
        "partner": partner_payload,
        "impersonator": impersonator_payload,
        "feature_flags": feature_flags,
    })


# ---------------------------------------------------------------------------
# OperatorScope management surface (US-S11-028)
#
# Read + grant + revoke from the System Admin > Operator scopes tab.
# Permission is tighter than the rest of the trigger family because
# OperatorScope decides who sees what personal data — only nsr_admin
# may write.


class OperatorScopeSerializer(serializers.ModelSerializer):
    """Read shape for the list view. Adds the username + GeographicUnit
    name (when resolvable) so the table can label each row without
    extra round-trips."""

    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.SerializerMethodField()
    scope_label = serializers.SerializerMethodField()

    class Meta:
        model = OperatorScope
        fields = (
            "id", "user", "username", "display_name",
            "scope_level", "scope_code", "scope_label",
            "active", "granted_at", "granted_by", "note",
        )
        read_only_fields = (
            "granted_at", "granted_by", "username", "display_name",
            "scope_label",
        )

    def get_display_name(self, obj) -> str:
        u = obj.user
        return (u.get_full_name() or u.username) if u else ""

    def get_scope_label(self, obj) -> str:
        """Human-readable scope label. For geographic levels look up
        GeographicUnit.name; for partner look up Partner.name; for
        national return "All regions"."""
        if obj.scope_level == ScopeLevel.NATIONAL:
            return "All regions (national)"
        if obj.scope_level == ScopeLevel.PARTNER:
            if not obj.scope_code:
                return "(no partner code)"
            from apps.partners.models import Partner
            p = Partner.objects.filter(code=obj.scope_code).first()
            return f"{p.name} ({p.code})" if p else obj.scope_code
        # Geographic levels resolve against GeographicUnit by (level, code).
        from apps.reference_data.models import GeographicUnit
        gu = GeographicUnit.objects.filter(
            level=obj.scope_level, code=obj.scope_code,
        ).first()
        return f"{gu.name} ({gu.code})" if gu else obj.scope_code


class BulkGrantRequestSerializer(serializers.Serializer):
    """Grant one user N OperatorScopes at the same scope_level. The
    Grant Scope modal uses this to assign "all parishes in District X"
    in one click."""

    user_id = serializers.IntegerField()
    scope_level = serializers.ChoiceField(choices=ScopeLevel.choices)
    # scope_codes may be empty when scope_level=national (one row with
    # blank code is the wildcard).
    scope_codes = serializers.ListField(
        child=serializers.CharField(max_length=64, allow_blank=True),
        allow_empty=True,
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=512,
    )


class BulkGrantResponseSerializer(serializers.Serializer):
    granted = OperatorScopeSerializer(many=True)
    skipped_existing = serializers.ListField(child=serializers.CharField())


class UserSearchItemSerializer(serializers.Serializer):
    """Compact identity for the Grant Scope modal's user picker."""
    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    groups = serializers.ListField(child=serializers.CharField())


def _validate_scope_codes(scope_level: str, scope_codes: list[str]) -> list[str]:
    """Validate every scope_code matches a real GeographicUnit (for
    geographic levels) or Partner (for partner). Returns the list
    unchanged; raises serializers.ValidationError on the first miss.

    national level: scope_codes must be [""] or [] — we coerce to
    [""] so the single wildcard row gets created. Anything else is
    a 400 because national has no sub-code semantics.
    """
    if scope_level == ScopeLevel.NATIONAL:
        non_empty = [c for c in scope_codes if c.strip()]
        if non_empty:
            raise serializers.ValidationError(
                "scope_level=national takes no scope_codes; supply [] or [''].",
            )
        return [""]
    if not scope_codes:
        raise serializers.ValidationError(
            f"scope_level={scope_level} requires at least one scope_code.",
        )
    if scope_level == ScopeLevel.PARTNER:
        from apps.partners.models import Partner
        known = set(
            Partner.objects.filter(code__in=scope_codes)
            .values_list("code", flat=True),
        )
        missing = [c for c in scope_codes if c not in known]
        if missing:
            raise serializers.ValidationError(
                f"unknown partner code(s): {sorted(missing)}",
            )
        return scope_codes
    # Geographic levels: each code must exist in GeographicUnit at
    # the requested level.
    from apps.reference_data.models import GeographicUnit
    known = set(
        GeographicUnit.objects
        .filter(level=scope_level, code__in=scope_codes)
        .values_list("code", flat=True),
    )
    missing = [c for c in scope_codes if c not in known]
    if missing:
        raise serializers.ValidationError(
            f"unknown {scope_level} code(s): {sorted(missing)}",
        )
    return scope_codes


@extend_schema_view(
    list=extend_schema(tags=["security"], summary="List operator scopes"),
    retrieve=extend_schema(tags=["security"], summary="Retrieve an operator scope"),
    destroy=extend_schema(
        tags=["security"], summary="Revoke an operator scope",
        description="Hard-delete + audit event. Mirrors how the Django admin's delete works."),
)
class OperatorScopeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Read + grant + revoke. Create is via bulk-grant only; single-
    POST is intentionally not exposed to keep one shape on the wire."""

    queryset = (
        OperatorScope.objects
        .select_related("user")
        .order_by("user__username", "scope_level", "scope_code")
    )
    serializer_class = OperatorScopeSerializer
    permission_classes = [IsOperatorScopeAdmin]
    filterset_fields = ["user", "scope_level", "active"]

    def get_queryset(self):
        # django-filter isn't installed; honour the filter params
        # manually so the console can drill by user / level.
        qs = super().get_queryset()
        params = self.request.query_params
        user_id = params.get("user")
        if user_id:
            qs = qs.filter(user_id=user_id)
        level = params.get("scope_level")
        if level:
            qs = qs.filter(scope_level=level)
        active = params.get("active")
        if active in ("true", "false"):
            qs = qs.filter(active=(active == "true"))
        return qs

    def perform_destroy(self, instance):
        actor = (getattr(self.request.user, "username", "") or "").strip() or "admin"
        emit_audit(
            "security.operator_scope.revoked", "operator_scope", str(instance.id),
            actor=actor,
            reason=(
                f"revoked {instance.scope_level}={instance.scope_code or '*'} "
                f"from {instance.user.username}"
            ),
        )
        instance.delete()

    @extend_schema(
        tags=["security"],
        summary="Grant N OperatorScopes to a user at one scope_level",
        description=(
            "Used by the System Admin > Operator scopes tab's Grant "
            "Scope modal. Validates every scope_code against "
            "GeographicUnit (or Partner for partner level). Idempotent: "
            "(user, scope_level, scope_code) tuples that already exist "
            "are reported in `skipped_existing` rather than 4xxing."
        ),
        request=BulkGrantRequestSerializer,
        responses={
            200: BulkGrantResponseSerializer,
            400: OpenApiResponse(description="unknown user, scope_code, or partner"),
            403: OpenApiResponse(description="caller lacks IsOperatorScopeAdmin"),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk-grant")
    def bulk_grant(self, request):
        ser = BulkGrantRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from django.contrib.auth import get_user_model
        User = get_user_model()  # noqa: N806 — matches Django convention
        try:
            target = User.objects.get(id=ser.validated_data["user_id"])
        except User.DoesNotExist:
            return Response(
                {"detail": f"user_id {ser.validated_data['user_id']} not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            codes = _validate_scope_codes(
                ser.validated_data["scope_level"],
                ser.validated_data["scope_codes"],
            )
        except serializers.ValidationError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        actor = (getattr(request.user, "username", "") or "").strip() or "admin"
        note = ser.validated_data.get("note", "") or ""
        granted: list[OperatorScope] = []
        skipped: list[str] = []
        for code in codes:
            scope, created = OperatorScope.objects.get_or_create(
                user=target,
                scope_level=ser.validated_data["scope_level"],
                scope_code=code,
                defaults={
                    "active": True,
                    "granted_by": actor,
                    "note": note,
                },
            )
            if created:
                granted.append(scope)
                emit_audit(
                    "security.operator_scope.granted", "operator_scope",
                    str(scope.id), actor=actor,
                    reason=(
                        f"granted {scope.scope_level}={scope.scope_code or '*'} "
                        f"to {target.username}"
                    ),
                )
            else:
                skipped.append(code or "*")
        return Response(
            BulkGrantResponseSerializer({
                "granted": granted, "skipped_existing": skipped,
            }).data,
        )


@extend_schema(
    tags=["security"],
    summary="Search users for the Grant Scope picker",
    description=(
        "Returns up to 50 users matching `q` (username or display "
        "name, case-insensitive). Permission IsOperatorScopeAdmin "
        "because the user list is a security surface."
    ),
    responses={200: UserSearchItemSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([IsOperatorScopeAdmin])
def user_search(request):
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()  # noqa: N806 — matches Django convention
    q = (request.query_params.get("q") or "").strip()
    qs = User.objects.all().order_by("username")
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q),
        )
    qs = qs[:50]
    out = [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.get_full_name() or u.username,
            "groups": list(u.groups.values_list("name", flat=True)),
        }
        for u in qs
    ]
    return Response(out)


# ---------------------------------------------------------------------------
# Impersonation (US-S11-042)
#
# Audit-bearing "Login as another user" for the System Admin console.
# Read-only mode is enforced by ImpersonationGuardMiddleware — this
# module just owns the start/stop endpoints.


class ImpersonateRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    # allow_blank + trim_whitespace=False so the service-level guard
    # ("Reason is required") fires consistently — the serializer would
    # otherwise reject whitespace-only with a different error shape.
    reason = serializers.CharField(
        max_length=512, allow_blank=True, trim_whitespace=False,
    )


@extend_schema(
    tags=["security"],
    summary="Start impersonating another user (US-S11-042)",
    description=(
        "Swaps the session's authenticated user over to `user_id`, "
        "stashing the original admin in session._impersonator_id. "
        "Only superusers or members of the `nsr_admin` group may "
        "impersonate; another superuser cannot be impersonated. "
        "Audit-bearing — emits security.impersonation.started "
        "naming both identities + reason."
    ),
    request=ImpersonateRequestSerializer,
    responses={
        200: OpenApiResponse(description="Impersonation started"),
        400: OpenApiResponse(description="Bad request (target invalid, etc)"),
        403: OpenApiResponse(description="Caller lacks impersonation permission"),
    },
)
@api_view(["POST"])
@permission_classes([IsOperatorScopeAdmin])
def impersonate_start(request):
    from .impersonation import ImpersonationError, start_impersonation
    ser = ImpersonateRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    try:
        actor, target = start_impersonation(
            request,
            target_user_id=ser.validated_data["user_id"],
            reason=ser.validated_data["reason"],
        )
    except ImpersonationError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({
        "ok": True,
        "impersonator": {"id": actor.id, "username": actor.username},
        "target": {
            "id": target.id,
            "username": target.username,
            "display_name": target.get_full_name() or target.username,
        },
    })


@extend_schema(
    tags=["security"],
    summary="Stop impersonating (US-S11-042)",
    description=(
        "Reverts the session back to the original admin. Exempt from "
        "the read-only middleware so an admin can always get out. "
        "Audit-bearing — emits security.impersonation.stopped."
    ),
    request=None,
    responses={
        200: OpenApiResponse(description="Reverted"),
        400: OpenApiResponse(description="No active impersonation"),
    },
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def impersonate_stop(request):
    from .impersonation import ImpersonationError, stop_impersonation
    try:
        impersonator, target_was = stop_impersonation(request)
    except ImpersonationError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({
        "ok": True,
        "impersonator": {"id": impersonator.id, "username": impersonator.username},
        "stopped_target": {"id": target_was.id, "username": target_was.username},
    })
