from django.contrib import admin

from .models import AuditEvent, OperatorScope


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only admin. AuditEvent is append-only — UI enforces what the
    Postgres trigger enforces structurally."""

    list_display = ("occurred_at", "action", "entity_type", "entity_id", "actor_id", "actor_kind")
    list_filter = ("action", "entity_type", "actor_kind")
    search_fields = ("entity_id", "actor_id", "reason")
    ordering = ("-occurred_at",)
    date_hierarchy = "occurred_at"

    readonly_fields = (
        "id", "occurred_at", "actor_id", "actor_kind", "action",
        "entity_type", "entity_id", "field_changes", "reason",
        "ip_address", "user_agent", "prev_hash_hex", "self_hash_hex",
    )
    exclude = ("prev_hash", "self_hash")

    @admin.display(description="prev_hash (hex)")
    def prev_hash_hex(self, obj):
        return obj.prev_hash.hex() if obj.prev_hash else "—"

    @admin.display(description="self_hash (hex)")
    def self_hash_hex(self, obj):
        return obj.self_hash.hex() if obj.self_hash else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OperatorScope)
class OperatorScopeAdmin(admin.ModelAdmin):
    """ABAC geographic scope per SAD §8.2. Grant by selecting the user
    and the (level, code) pair that matches the GeographicUnit they
    cover. `national` is the wildcard for NSR Unit Coordinator / DPO."""

    list_display = ("user", "scope_level", "scope_code", "active",
                    "expires_at", "in_force", "granted_at", "granted_by")
    list_filter = ("scope_level", "active")
    search_fields = ("user__username", "scope_code", "granted_by")
    readonly_fields = ("granted_at",)
    raw_id_fields = ("user",)

    @admin.display(boolean=True, description="In force now?")
    def in_force(self, obj):
        """Expiry takes effect the moment it passes, so `active` alone no
        longer tells you whether a scope grants anything."""
        from django.utils import timezone
        return bool(
            obj.active
            and (obj.expires_at is None or obj.expires_at > timezone.now()),
        )


# --- operator administration -------------------------------------------------
#
# Creating an operator means three separate things: an account, a ROLE (Django
# Group, from the apps.security.roles catalogue) and one or more geographic
# ATTRIBUTES (OperatorScope). Django's stock UserAdmin covers the first two and
# knows nothing about the third, so an administrator had to visit two screens
# and remember that a role without a scope sees nothing at all — the mixins
# fail closed.
#
# This puts all three on one page, shows the permissions a role actually
# carries, and warns when the combination cannot see any data.

from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils.html import format_html  # noqa: E402

from apps.security import roles as role_catalogue  # noqa: E402


class OperatorScopeInline(admin.TabularInline):
    """Geographic / partner attributes, edited alongside the account."""

    model = OperatorScope
    extra = 0
    fields = ("scope_level", "scope_code", "active", "expires_at",
              "granted_by", "note")
    readonly_fields = ("granted_at",)
    verbose_name = "ABAC scope"
    verbose_name_plural = "ABAC scopes (attributes)"


class OperatorAdmin(DjangoUserAdmin):
    """User admin with roles, effective permissions and ABAC scopes together."""

    inlines = [OperatorScopeInline]
    list_display = (
        "username", "email", "is_active", "roles_display",
        "scopes_display", "access_warning",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")
    readonly_fields = ("last_login", "date_joined", "effective_permissions",
                       "role_guidance")

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return super().get_fieldsets(request, obj)
        return (
            (None, {"fields": ("username", "password")}),
            ("Personal info", {"fields": ("first_name", "last_name", "email")}),
            ("Roles", {
                "fields": ("groups", "role_guidance", "effective_permissions"),
                "description": (
                    "Roles come from the apps.security.roles catalogue "
                    "(ADR-0028). Permissions are carried BY the role — assign "
                    "the role, not individual permissions."
                ),
            }),
            ("Account status", {
                "fields": ("is_active", "is_staff", "is_superuser"),
                "description": (
                    "is_superuser bypasses ABAC and every permission check. "
                    "Use it for break-glass accounts only."
                ),
            }),
            ("Advanced: individual permissions", {
                "classes": ("collapse",),
                "fields": ("user_permissions",),
                "description": (
                    "Prefer roles. Direct grants here are invisible to the "
                    "role catalogue and will not be reproduced by Keycloak "
                    "when identity moves there."
                ),
            }),
            ("Dates", {"fields": ("last_login", "date_joined")}),
        )

    # --- display helpers ---------------------------------------------------

    @admin.display(description="Roles")
    def roles_display(self, obj):
        names = list(obj.groups.values_list("name", flat=True))
        if not names:
            return "—"
        labels = []
        for n in names:
            role = role_catalogue.BY_CODE.get(n)
            labels.append(role.label if role else n)
        return ", ".join(labels)

    @admin.display(description="ABAC scopes")
    def scopes_display(self, obj):
        rows = obj.operator_scopes.effective() if hasattr(
            obj, "operator_scopes") else OperatorScope.objects.effective().filter(user=obj)
        parts = [f"{s.scope_level}:{s.scope_code or '*'}" for s in rows]
        return ", ".join(parts) if parts else "—"

    @admin.display(description="Can see data?")
    def access_warning(self, obj):
        if obj.is_superuser:
            return format_html('<span style="color:#B8741A">superuser '
                               '(bypasses ABAC)</span>')
        has_scope = OperatorScope.objects.effective().filter(user=obj).exists()
        has_role = obj.groups.exists()
        if has_scope and has_role:
            return format_html('<span style="color:#2E7D32">yes</span>')
        missing = []
        if not has_role:
            missing.append("role")
        if not has_scope:
            missing.append("scope")
        # The mixins fail closed, so a missing scope means zero rows rather
        # than an error — worth saying out loud on the changelist.
        return format_html(
            '<span style="color:#A93226">no — missing {}</span>',
            " and ".join(missing),
        )

    @admin.display(description="Permissions carried by these roles")
    def effective_permissions(self, obj):
        codes = set()
        for name in obj.groups.values_list("name", flat=True):
            codes |= role_catalogue.permissions_for(name)
        if obj.is_superuser:
            return format_html(
                "<b>all</b> — is_superuser bypasses every permission check",
            )
        if not codes:
            return "none — this account can read within scope but change nothing"
        return format_html(
            "<br>".join(
                f"<code>{c}</code> — {role_catalogue.PERMISSIONS[c]}"
                for c in sorted(codes)
            ),
        )

    @admin.display(description="Scope expected for these roles")
    def role_guidance(self, obj):
        names = list(obj.groups.values_list("name", flat=True))
        if not names:
            return "Assign a role, then add the matching ABAC scope below."
        lines = []
        for n in sorted(names):
            role = role_catalogue.BY_CODE.get(n)
            if not role:
                lines.append(f"<code>{n}</code> — not in the catalogue")
                continue
            lines.append(
                f"<code>{role.code}</code> — usually scoped at "
                f"<b>{role.default_scope}</b>"
                + (" (scope_code = Partner.code)" if role.external else ""),
            )
        return format_html("<br>".join(lines))


# Replace the stock User admin with the operator-aware one.
admin.site.unregister(User)
admin.site.register(User, OperatorAdmin)
