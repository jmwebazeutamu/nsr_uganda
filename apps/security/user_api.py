"""Account administration endpoints, for the console's User management screen.

Gated on `nsr_admin` alone — narrower than the admin console's own gate,
which admits five groups. A statistics user or the DPO can open the
console and will not see this surface at all.

Every write delegates to user_management, which holds the guards and the
audit writes; nothing here touches the ORM directly.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import user_management as um

User = get_user_model()

USER_ADMIN_GROUPS = ("nsr_admin",)


class IsUserAdmin(permissions.BasePermission):
    """Superusers always pass; otherwise `nsr_admin` membership.

    403 rather than 404 so an operator who reached this by a stale link
    learns why instead of concluding the feature does not exist.
    """

    message = (
        "User administration requires membership in: "
        + ", ".join(USER_ADMIN_GROUPS) + "."
    )

    def has_permission(self, request, view) -> bool:
        u = request.user
        if u is None or not getattr(u, "is_authenticated", False):
            return False
        if getattr(u, "is_superuser", False):
            return True
        return u.groups.filter(name__in=USER_ADMIN_GROUPS).exists()


class ManagedUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    manageable = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "username", "first_name", "last_name", "email",
            "is_active", "is_staff", "is_superuser", "last_login",
            "date_joined", "roles", "manageable",
        )
        read_only_fields = fields

    def get_roles(self, obj) -> list[str]:
        return sorted(g.name for g in obj.groups.all())

    def get_manageable(self, obj) -> bool:
        """False for superusers. The screen greys the row rather than
        offering actions that will be refused."""
        return not obj.is_superuser


class UserAdminViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet,
):
    """Read, plus the four lifecycle actions. No destroy: accounts are
    deactivated, never deleted — the audit chain references users by
    username and deleting one leaves the trail pointing at nobody."""

    queryset = User.objects.prefetch_related("groups").order_by("username")
    serializer_class = ManagedUserSerializer
    permission_classes = [IsUserAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q)
                | Q(last_name__icontains=q) | Q(email__icontains=q),
            )
        state = (self.request.query_params.get("state") or "").strip()
        if state == "active":
            qs = qs.filter(is_active=True)
        elif state == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def _fail(self, exc) -> Response:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(tags=["security"], summary="Role and scope-level catalogues",
                   responses={200: OpenApiResponse(description="Catalogues")})
    @action(detail=False, methods=["get"], url_path="roles")
    def roles(self, request):
        """Read-only, and the single source for both lists the screen
        needs: roles are defined in code and synced into Groups
        (ADR-0028), scope levels come from ScopeLevel. Neither is written
        here, and neither is duplicated in the console — a hand-kept copy
        of the scope levels is exactly what left region, sub_region and
        village unassignable."""
        return Response({
            "roles": um.role_catalogue(),
            "scope_levels": um.scope_levels(),
        })

    @extend_schema(tags=["security"], summary="Create an account")
    @action(detail=False, methods=["post"], url_path="create")
    def create_account(self, request):
        try:
            user, temporary = um.create_user(
                actor=request.user,
                username=request.data.get("username", ""),
                first_name=request.data.get("first_name", ""),
                last_name=request.data.get("last_name", ""),
                email=request.data.get("email", ""),
                roles=request.data.get("roles") or [],
                reason=request.data.get("reason", ""),
            )
        except um.UserManagementError as exc:
            return self._fail(exc)
        return Response(
            {
                "user": ManagedUserSerializer(user).data,
                # Shown once. Not retrievable afterwards by anyone.
                "temporary_password": temporary,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["security"], summary="Edit contact details")
    @action(detail=True, methods=["post"], url_path="profile")
    def edit_profile(self, request, pk=None):
        """Name and email only. The username is not editable — see
        user_management.update_profile for why."""
        try:
            user = um.update_profile(
                actor=request.user, user=self.get_object(),
                first_name=request.data.get("first_name"),
                last_name=request.data.get("last_name"),
                email=request.data.get("email"),
                reason=request.data.get("reason", ""),
            )
        except um.UserManagementError as exc:
            return self._fail(exc)
        return Response(ManagedUserSerializer(user).data)

    @extend_schema(tags=["security"], summary="Set a user's roles")
    @action(detail=True, methods=["post"], url_path="roles")
    def set_roles(self, request, pk=None):
        try:
            user = um.set_roles(
                actor=request.user, user=self.get_object(),
                roles=request.data.get("roles") or [],
                reason=request.data.get("reason", ""),
            )
        except um.UserManagementError as exc:
            return self._fail(exc)
        return Response(ManagedUserSerializer(user).data)

    @extend_schema(tags=["security"], summary="Activate or deactivate")
    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        try:
            user = um.set_active(
                actor=request.user, user=self.get_object(),
                active=bool(request.data.get("active")),
                reason=request.data.get("reason", ""),
            )
        except um.UserManagementError as exc:
            return self._fail(exc)
        return Response(ManagedUserSerializer(user).data)

    @extend_schema(tags=["security"], summary="Reset a password")
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        try:
            result = um.reset_password(
                actor=request.user, user=self.get_object(),
                method=request.data.get("method", "temporary"),
                reason=request.data.get("reason", ""),
                reset_url_base=request.build_absolute_uri("/").rstrip("/"),
            )
        except um.UserManagementError as exc:
            return self._fail(exc)
        return Response(result)
