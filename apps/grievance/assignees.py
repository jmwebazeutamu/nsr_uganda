"""Who a grievance or task can be assigned to, and how to reach them.

`Grievance.assigned_to` and `GrievanceTask.assigned_to` are CharFields
holding a username — "String until Keycloak (US-S2-002) lands", as the
models say. That was fine while nothing depended on the value meaning
anything. Two things now do:

  * the console offers a picker rather than a free-text box, because
    the four names it used to offer — "Adong Florence · CDO Tapac" and
    friends — were invented, and an invented assignee is a task nobody
    is doing;
  * an assignment sends the assignee an email, which needs an address.

So the username is resolved against the real user catalogue here. The
column stays a CharField — this is not the Keycloak migration — but a
value that does not name an active user is rejected at the service
boundary rather than stored and discovered later.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model


class UnknownAssignee(Exception):
    """The username does not name an active MIS user."""


def resolve(username: str):
    """The active User behind `username`, or raise UnknownAssignee.

    Matched case-insensitively on username: the picker sends what the
    catalogue served, but a hand-typed value or an older client should
    not fail on capitalisation alone.
    """
    username = (username or "").strip()
    if not username:
        raise UnknownAssignee("no assignee given")
    user = (
        get_user_model().objects
        .filter(username__iexact=username, is_active=True)
        .first()
    )
    if user is None:
        raise UnknownAssignee(
            f"{username!r} is not an active MIS user — pick an assignee "
            "from the directory",
        )
    return user


def display_name(user) -> str:
    return user.get_full_name() or user.username


def email_for(user) -> str:
    return (user.email or "").strip()
