"""Authorisation for human UPD review actions.

The routing rule captures the role responsible for a request at submission
time. This module translates that stored role through the security role
catalogue, then evaluates the authenticated user's existing group membership.
It deliberately does not maintain a second UPD role matrix.
"""

from __future__ import annotations

from apps.security.roles import ADR0006_TO_CODE, DATA_APPROVE, permissions_for

from .models import ChangeStatus


def canonical_role_code(required_role: str) -> str:
    """Resolve a configured role code to the application role catalogue."""
    return ADR0006_TO_CODE.get(required_role, required_role)


def reviewer_denial(user, change_request) -> str | None:
    """Return a displayable denial reason, or ``None`` when review is allowed."""
    if not getattr(user, "is_authenticated", False):
        return "An authenticated reviewer is required."
    if getattr(user, "is_superuser", False):
        return None
    role_code = canonical_role_code(change_request.required_role)
    if not role_code:
        return "This request has no assigned reviewer role."
    if DATA_APPROVE not in permissions_for(role_code):
        return f"Configured reviewer role {role_code!r} has no data-approval permission."
    user_roles = set(user.groups.values_list("name", flat=True))
    if role_code not in user_roles:
        return f"This request is assigned to the {role_code!r} reviewer role."
    return None


def allowed_actions(user, change_request) -> dict[str, dict[str, object]]:
    """Return the UI/API action contract for one canonical request row."""
    review_denial = reviewer_denial(user, change_request)
    self_denial = (
        "AC-UPD-NO-SELF-APPROVE: requester cannot review their own change request."
        if getattr(user, "get_username", lambda: "")() == change_request.requester
        else None
    )
    denial = self_denial or review_denial
    pending = change_request.status == ChangeStatus.PENDING_APPROVAL
    held = change_request.status == ChangeStatus.ON_HOLD

    def state(available: bool, reason: str | None = None):
        return {"allowed": bool(available), "reason": reason or ""}

    return {
        "approve": state(pending and not denial, denial or "Request is not awaiting approval."),
        "reject": state(pending and not denial, denial or "Request is not awaiting approval."),
        "hold": state(pending and not denial, denial or "Request is not awaiting approval."),
        "release": state(held and not denial, denial or "Request is not on hold."),
    }


def assert_action_allowed(user, change_request, action: str) -> None:
    """Raise the DRF-native denial used by every review endpoint."""
    from rest_framework.exceptions import PermissionDenied

    if action not in allowed_actions(user, change_request):
        raise PermissionDenied("Unknown UPD review action.")
    # State transitions remain the service layer's responsibility and return
    # its existing 400 precondition response. Permission and segregation-of-
    # duties failures are 403s, regardless of the current workflow state.
    denial = reviewer_denial(user, change_request)
    if getattr(user, "get_username", lambda: "")() == change_request.requester:
        denial = "AC-UPD-NO-SELF-APPROVE: requester cannot review their own change request."
    if denial:
        raise PermissionDenied(denial)
