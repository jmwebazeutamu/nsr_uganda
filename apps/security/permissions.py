"""Enforce the eight TOR data permissions (US-063 / ADR-0028).

ADR-0028 declared and assigned the permissions but deliberately stopped short
of enforcing them, to keep the authorisation diff reviewable. This is that
follow-on: a DRF permission class that maps the HTTP method onto the matching
TOR action and checks it.

It composes with, rather than replaces, the existing controls:

* `IsAuthenticated` still decides *whether* you are anybody;
* ABAC (`apps.security.abac`) still decides *which rows* you can see;
* this decides *what kind of action* your role may take at all.

A view can name its own permission when the method is not the whole story —
approving a change request is a POST, but it is Data Approval, not Data Entry:

    class ChangeRequestViewSet(...):
        data_permission_map = {"approve": roles.DATA_APPROVE,
                               "reject": roles.DATA_APPROVE}

Superusers pass. That is Django's own `has_perm` contract, and the break-glass
account depends on it.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission

from apps.security import roles

#: Default HTTP method -> TOR permission. SAFE_METHODS are Data View; the
#: write verbs map onto the closest TOR action.
METHOD_PERMISSION: dict[str, str] = {
    # SAFE_METHODS are deliberately absent. Reads are already gated twice --
    # IsAuthenticated decides whether you are anybody, and ABAC decides which
    # rows you may see, which is the mechanism SAD 8.2 actually names. Adding
    # Data View as a third gate would mean every operator needs a Group AND an
    # OperatorScope where the scope alone is sufficient and already encodes
    # who they are; the practical effect would be to lock out correctly-scoped
    # operators over a missing group membership.
    #
    # Data View is still assigned to every role and can be demanded explicitly
    # by a view via `data_permission` where a surface warrants it (bulk export
    # previews, the Data Explorer). The action classes earn their keep on
    # writes and extracts.
    "POST": roles.DATA_ENTRY,
    "PUT": roles.DATA_MODIFY,
    "PATCH": roles.DATA_MODIFY,
    "DELETE": roles.DATA_DELETE,
}


_UNSET = object()


def required_permission(request, view) -> str | None:
    """The TOR permission this request needs, or None to abstain."""
    action = getattr(view, "action", None)
    per_action = getattr(view, "data_permission_map", None) or {}
    if action and action in per_action:
        return per_action[action]
    explicit = getattr(view, "data_permission", _UNSET)
    if explicit is not _UNSET:
        # An explicit None/"" means "this endpoint needs no action-class
        # permission" -- distinct from the attribute being absent, which falls
        # through to the method mapping. Used by endpoints that POST but do not
        # create anything.
        return explicit or None
    return METHOD_PERMISSION.get(request.method)


class HasDataPermission(BasePermission):
    """Require the TOR permission matching this request's method/action."""

    message = "Your role does not carry the permission this action requires."

    def has_permission(self, request, view) -> bool:
        if not getattr(settings, "NSR_ENFORCE_DATA_PERMISSIONS", False):
            return True

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            # Let IsAuthenticated produce the 401/403 — this class only rules
            # on *what* an authenticated principal may do.
            return True
        if user.is_superuser:
            return True

        codename = required_permission(request, view)
        if codename is None:
            return True

        if user.has_perm(f"security.{codename}"):
            return True

        self.message = (
            f"This action requires the '{codename.replace('_', ' ')}' permission, "
            "which none of your roles carry."
        )
        return False
