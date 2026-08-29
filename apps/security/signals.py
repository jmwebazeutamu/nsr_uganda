"""Apply the role catalogue's default scope when a role is granted (G7).

`m2m_changed` on `User.groups` is the only hook that catches every route into
role assignment — the Django admin, the shell, `create_operator`, a data
migration, and (later) the Keycloak claim mapper — without each of them having
to remember.

Only `post_add` is handled. `post_remove` deliberately does nothing: see
apps.security.scope_provisioning for why revocation is left to the DPO's
sweep rather than happening on a group edit.
"""

from __future__ import annotations

import logging

from django.contrib.auth.models import User
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(m2m_changed, sender=User.groups.through,
          dispatch_uid="security.apply_default_scopes_on_role_grant")
def apply_default_scopes_on_role_grant(sender, instance, action, reverse,
                                       pk_set, **kwargs):
    if action != "post_add":
        return

    from apps.security.scope_provisioning import ensure_default_scopes

    # `reverse` means the Group side was edited (group.user_set.add(...)), so
    # `instance` is the Group and pk_set holds user ids.
    if reverse:
        users = User.objects.filter(pk__in=pk_set or ())
    else:
        users = [instance]

    for user in users:
        try:
            result = ensure_default_scopes(user)
        except Exception:  # noqa: BLE001 — never break a role assignment
            logger.exception(
                "could not apply default scopes for %s", getattr(user, "pk", "?"),
            )
            continue

        if result.needs_manual_scope:
            # Not an error: these roles genuinely cannot be scoped without a
            # code. Logged so the omission leaves a trace even when the grant
            # happens outside the admin, where the "Can see data?" column
            # would have shown it.
            logger.info(
                "user %s holds %s but has no scope at %s — assign an "
                "OperatorScope or the account sees nothing",
                user.get_username(),
                ", ".join(r for r, _ in result.needs_manual_scope),
                ", ".join(sorted({lvl for _, lvl in result.needs_manual_scope})),
            )
