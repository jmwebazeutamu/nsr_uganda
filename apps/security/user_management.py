"""Account lifecycle: create, reset, deactivate, role membership.

The seam. Every write goes through here rather than through the ORM at
the view, so the day Keycloak becomes the identity provider (CLAUDE.md
locks it as the auth stack; it is not wired today, and settings says so)
the screens and the API keep their shape and only these functions change.

Three rules the callers do not get to bend:

  * An admin cannot change their own roles. Self-promotion is the
    cheapest escalation there is, and an audit entry proving you did it
    is not the same as being unable to.
  * No action may target a superuser. Superusers remain manageable only
    through the Django admin, which stays available.
  * Accounts are deactivated, never deleted. The audit chain references
    users by username; deleting one leaves an audit trail pointing at
    nobody.

Roles are membership only. The catalogue lives in roles.py and is
materialised into Groups by `manage.py sync_roles` (ADR-0028) — nothing
here creates, renames or deletes a Group.
"""

from __future__ import annotations

import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .audit import emit as emit_audit
from .roles import ROLES

User = get_user_model()

# Roles that make an account privileged. Granting one is the action most
# worth being deliberate about; the API flags it in the audit reason.
PRIVILEGED_ROLES = frozenset({"nsr_admin", "nsr_security", "dpo", "nsr_dba"})

# Unambiguous alphabet: no O/0, l/1/I. A temporary password is read off a
# screen and typed by someone else, often over a phone.
_TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
TEMP_PASSWORD_LENGTH = 14


class UserManagementError(Exception):
    """The action is refused. The message is shown to the operator."""


def role_catalogue() -> list[dict]:
    """The assignable roles, from the one catalogue. Read-only here."""
    existing = set(Group.objects.values_list("name", flat=True))
    return [
        {
            "code": r.code,
            "label": r.label,
            "default_scope": r.default_scope,
            "external": r.external,
            "privileged": r.code in PRIVILEGED_ROLES,
            # A role in the catalogue with no Group has not been synced;
            # assigning it would silently do nothing.
            "assignable": r.code in existing,
        }
        for r in ROLES
    ]


def _guard(actor, target: User | None, *, changing_roles: bool = False) -> None:
    if target is not None and target.is_superuser:
        raise UserManagementError(
            "Superuser accounts cannot be managed here. Use the Django "
            "admin, which remains available for exactly this case.",
        )
    if changing_roles and target is not None and actor is not None:
        if getattr(actor, "pk", None) == target.pk:
            raise UserManagementError(
                "You cannot change your own roles. Ask another "
                "administrator, so the change has two people behind it.",
            )


def generate_temporary_password() -> str:
    return "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(TEMP_PASSWORD_LENGTH))


def _actor_name(actor) -> str:
    return getattr(actor, "username", "") or "system"


@transaction.atomic
def create_user(
    *, actor, username: str, first_name: str = "", last_name: str = "",
    email: str = "", roles: list[str] | None = None, reason: str = "",
) -> tuple[User, str]:
    """Create an account with a temporary password.

    Returns (user, temporary_password). The password is returned once and
    never stored in readable form — if the operator loses it, the reset
    flow is the way back, not a lookup.
    """
    username = (username or "").strip()
    if not username:
        raise UserManagementError("A username is required.")
    if User.objects.filter(username__iexact=username).exists():
        raise UserManagementError(f"An account named {username!r} already exists.")

    temporary = generate_temporary_password()
    user = User.objects.create_user(
        username=username, email=(email or "").strip(),
        first_name=(first_name or "").strip(), last_name=(last_name or "").strip(),
        password=temporary,
    )
    # Never through this screen. is_staff gates the Django admin, and an
    # account created here has no business gaining that quietly.
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["is_staff", "is_superuser"])

    if roles:
        set_roles(actor=actor, user=user, roles=roles,
                  reason=reason or "assigned at account creation")

    emit_audit(
        "create", "user", str(user.pk), actor=_actor_name(actor),
        reason=reason or "account created",
        field_changes={"username": username, "email": user.email,
                       "roles": sorted(roles or [])},
    )
    return user, temporary


@transaction.atomic
def set_roles(*, actor, user: User, roles: list[str], reason: str = "") -> User:
    """Replace a user's role membership. Membership only — see module docstring."""
    _guard(actor, user, changing_roles=True)
    if not reason or not reason.strip():
        raise UserManagementError("A reason is required for a role change.")

    wanted = {r.strip() for r in roles if r and r.strip()}
    known = {r["code"] for r in role_catalogue()}
    unknown = sorted(wanted - known)
    if unknown:
        raise UserManagementError(
            f"Not roles in the catalogue: {', '.join(unknown)}. Roles are "
            f"defined in apps/security/roles.py and synced with "
            f"manage.py sync_roles.",
        )
    groups = list(Group.objects.filter(name__in=wanted))
    missing = sorted(wanted - {g.name for g in groups})
    if missing:
        raise UserManagementError(
            f"These roles exist in the catalogue but have no Group yet: "
            f"{', '.join(missing)}. Run manage.py sync_roles first.",
        )

    before = sorted(user.groups.values_list("name", flat=True))
    user.groups.set(groups)
    after = sorted(wanted)
    if before != after:
        granted = sorted(set(after) - set(before))
        emit_audit(
            "update", "user", str(user.pk), actor=_actor_name(actor),
            reason=(
                f"roles changed{' (privileged)' if set(granted) & PRIVILEGED_ROLES else ''}"
                f": {reason.strip()}"
            ),
            field_changes={"roles_before": before, "roles_after": after},
        )
    return user


@transaction.atomic
def set_active(*, actor, user: User, active: bool, reason: str = "") -> User:
    """Deactivate or reactivate. Never deletes — see module docstring."""
    _guard(actor, user)
    if not reason or not reason.strip():
        raise UserManagementError(
            "A reason is required: someone will ask later why this account "
            "was disabled.",
        )
    if getattr(actor, "pk", None) == user.pk and not active:
        raise UserManagementError("You cannot deactivate your own account.")
    if user.is_active == active:
        return user

    user.is_active = active
    user.save(update_fields=["is_active"])
    emit_audit(
        "update", "user", str(user.pk), actor=_actor_name(actor),
        reason=f"{'reactivated' if active else 'deactivated'}: {reason.strip()}",
        field_changes={"is_active": active},
    )
    return user


@transaction.atomic
def reset_password(
    *, actor, user: User, method: str = "temporary", reason: str = "",
    reset_url_base: str = "",
) -> dict:
    """Reset a password by one of two routes.

    `temporary` generates a password and returns it once, for an operator
    with no working mailbox — which is most of them, and is exactly the
    case an email-only reset fails.

    `link` emails a time-limited link and returns nothing; the admin never
    learns the password.
    """
    _guard(actor, user)
    if not reason or not reason.strip():
        raise UserManagementError("A reason is required for a password reset.")
    if method not in ("temporary", "link"):
        raise UserManagementError(f"Unknown reset method {method!r}.")

    if method == "link":
        if not user.email:
            raise UserManagementError(
                f"{user.username} has no email address, so a link cannot be "
                f"sent. Use a temporary password instead.",
            )
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        link = f"{reset_url_base.rstrip('/')}/reset/{uid}/{token}/"
        send_mail(
            subject="NSR MIS — password reset",
            message=render_to_string(
                "registration/password_reset_email_body.txt",
                {"user": user, "link": link},
            ),
            from_email=None, recipient_list=[user.email], fail_silently=False,
        )
        emit_audit(
            "update", "user", str(user.pk), actor=_actor_name(actor),
            reason=f"password reset link emailed: {reason.strip()}",
            field_changes={"method": "link", "email": user.email},
        )
        return {"method": "link", "sent_to": user.email}

    temporary = generate_temporary_password()
    user.set_password(temporary)
    user.save(update_fields=["password"])
    emit_audit(
        "update", "user", str(user.pk), actor=_actor_name(actor),
        # The password itself is never written to the audit chain.
        reason=f"temporary password issued: {reason.strip()}",
        field_changes={"method": "temporary"},
    )
    return {"method": "temporary", "temporary_password": temporary}
