"""Operator impersonation — US-S11-042.

Session-based "Login as another user" for the System Admin console.
Audit-bearing, refuses to impersonate admins, and the
ImpersonationGuardMiddleware blocks every non-safe HTTP method while
the impersonator session is active (the stop endpoint itself is
explicitly exempt). The intent is debuggability — letting an admin
see exactly what a partner-affiliated operator sees, NOT to act on
their behalf.

Session keys:
- `_auth_user_id`        — set by django.contrib.auth (current user)
- `_auth_user_backend`   — set by django.contrib.auth
- `_impersonator_id`     — the original admin's pk, persisted only
                           during an active impersonation
- `_impersonator_reason` — reason captured at start (echoed in
                           the topbar banner)
"""

from __future__ import annotations

from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.http import JsonResponse

from .audit import emit as emit_audit

SESSION_KEY_IMPERSONATOR_ID = "_impersonator_id"
SESSION_KEY_IMPERSONATOR_REASON = "_impersonator_reason"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Endpoints exempt from the read-only guard while impersonating.
# `stop` MUST be reachable so the admin can revert; `me` is read-only
# but happens to be a GET anyway.
GUARD_EXEMPT_PATHS = (
    "/api/v1/security/impersonate/stop/",
)


class ImpersonationError(Exception):
    """Refusal at the service layer — actor lacks permission, target
    is themselves another admin, target == actor, etc."""


def _is_admin(user) -> bool:
    """Who can impersonate. Superusers always pass; otherwise the
    nsr_admin Django group (seeded by admin_console.0001) is the
    operational admin role."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name="nsr_admin").exists()


def start_impersonation(
    request, *, target_user_id: int, reason: str,
) -> tuple[object, object]:
    """Swap the session over to `target_user_id`. Returns
    (impersonator, target). Raises ImpersonationError on refusal.

    The audit event is emitted as the ORIGINAL admin so the trail
    answers "who decided to impersonate?" cleanly.
    """
    actor = request.user
    if not _is_admin(actor):
        raise ImpersonationError(
            "Impersonation requires superuser or nsr_admin membership.",
        )
    if not reason or not reason.strip():
        raise ImpersonationError(
            "Reason is required — the audit trail is the only paper "
            "record of why an admin acted as another user.",
        )
    if SESSION_KEY_IMPERSONATOR_ID in request.session:
        raise ImpersonationError(
            "Already impersonating — stop the current session before "
            "starting another.",
        )

    user_model = get_user_model()
    try:
        target = user_model.objects.get(id=target_user_id)
    except user_model.DoesNotExist as exc:
        raise ImpersonationError(
            f"user_id {target_user_id} not found.",
        ) from exc
    if target.id == actor.id:
        raise ImpersonationError("You can't impersonate yourself.")
    if target.is_superuser:
        # Defense-in-depth: an admin shouldn't be able to leapfrog
        # into another admin's identity. The audit chain still names
        # the actor either way, but blocking this at the service
        # narrows the impersonation surface to non-admin operators.
        raise ImpersonationError(
            "Cannot impersonate another superuser.",
        )

    # Capture the original session identity BEFORE swapping. We
    # store the impersonator's pk + auth backend + session-auth-hash
    # so the stop endpoint can revert cleanly. The hash matters
    # because Django's AuthenticationMiddleware verifies it on every
    # request — without restoring it, the original user would be
    # auto-logged-out on stop.
    impersonator_id = request.session.get("_auth_user_id")
    impersonator_backend = request.session.get("_auth_user_backend")
    impersonator_hash = request.session.get(HASH_SESSION_KEY)
    if impersonator_id is None or impersonator_backend is None:
        raise ImpersonationError(
            "No active session to impersonate from.",
        )
    request.session[SESSION_KEY_IMPERSONATOR_ID] = impersonator_id
    request.session["_impersonator_backend"] = impersonator_backend
    request.session["_impersonator_hash"] = impersonator_hash or ""
    request.session[SESSION_KEY_IMPERSONATOR_REASON] = reason.strip()
    # Swap the auth-id + session-auth-hash over so
    # AuthenticationMiddleware loads `target` on the next request.
    # If we leave the impersonator's hash in place, Django will
    # invalidate the session (target's password hash won't match)
    # and silently log the user out → AnonymousUser → 403.
    request.session["_auth_user_id"] = str(target.id)
    request.session[HASH_SESSION_KEY] = target.get_session_auth_hash()
    # request.user keeps pointing at actor for THIS request, so the
    # downstream view sees the original — which is what we want for
    # the audit emission below.

    emit_audit(
        "security.impersonation.started", "user", str(target.id),
        actor=actor.username,
        reason=reason.strip(),
        field_changes={
            "impersonator_id": impersonator_id,
            "impersonator_username": actor.username,
            "target_id": target.id,
            "target_username": target.username,
        },
    )
    return actor, target


def stop_impersonation(request) -> tuple[object, object]:
    """Revert the session to the original admin. Returns
    (impersonator, target_that_was_active). Raises ImpersonationError
    when there's nothing to stop."""
    impersonator_id = request.session.get(SESSION_KEY_IMPERSONATOR_ID)
    impersonator_backend = request.session.get("_impersonator_backend")
    if impersonator_id is None:
        raise ImpersonationError("No active impersonation session.")
    user_model = get_user_model()
    try:
        impersonator = user_model.objects.get(id=impersonator_id)
    except user_model.DoesNotExist as exc:
        raise ImpersonationError(
            "Impersonator user no longer exists. Log out and log "
            "back in to recover your session.",
        ) from exc
    target = request.user  # before swap

    request.session["_auth_user_id"] = str(impersonator.id)
    if impersonator_backend:
        request.session["_auth_user_backend"] = impersonator_backend
    # Restore the original session-auth-hash too so the next request
    # validates cleanly under AuthenticationMiddleware.
    request.session[HASH_SESSION_KEY] = (
        request.session.get("_impersonator_hash")
        or impersonator.get_session_auth_hash()
    )
    request.session.pop(SESSION_KEY_IMPERSONATOR_ID, None)
    request.session.pop("_impersonator_backend", None)
    request.session.pop("_impersonator_hash", None)
    reason = request.session.pop(SESSION_KEY_IMPERSONATOR_REASON, "")

    emit_audit(
        "security.impersonation.stopped", "user", str(target.id),
        actor=impersonator.username,
        reason=reason or "operator-initiated stop",
        field_changes={
            "impersonator_id": impersonator.id,
            "target_id": target.id,
            "target_username": target.username,
        },
    )
    return impersonator, target


def is_impersonating(request) -> bool:
    return bool(
        getattr(request, "session", None)
        and request.session.get(SESSION_KEY_IMPERSONATOR_ID),
    )


class ImpersonationGuardMiddleware:
    """Blocks non-safe HTTP methods while an impersonation session is
    active. Read-only impersonation is the safer default — the admin
    can SEE what the target sees but can't write on their behalf.
    The /impersonate/stop/ endpoint is exempt so the admin can always
    get out."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in SAFE_METHODS
            and is_impersonating(request)
            and request.path not in GUARD_EXEMPT_PATHS
        ):
            return JsonResponse(
                {"detail": (
                    "This session is impersonating another user. "
                    "Writes are disabled in impersonation mode — stop "
                    "impersonating to act as yourself again."
                )},
                status=403,
            )
        return self.get_response(request)
