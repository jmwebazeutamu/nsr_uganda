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
from django.db.models import Q


class UnknownAssignee(Exception):
    """The username does not name an active MIS user."""


class IneligibleAssignee(Exception):
    """The user exists, but cannot carry this case.

    Either their role does not hold the case's tier, or their
    geographic scope does not reach the household the case is about.
    """


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


# --- who may carry a case (QA P2.10) ---------------------------------
#
# The picker listed every user in the directory, active or not, with no
# regard for what the case needed. So an L3 District case could be
# assigned to an enumerator in another sub-region — a person with
# neither the authority to decide it nor the scope to open it. They
# would receive the email, click through, and get a 404 on their own
# work queue.
#
# Two conditions, and a deliberate third exemption:
#
#   * role — the tier's required_role, from the GrmTierRule ladder;
#   * scope — their OperatorScope must cover the household, using the
#     same helper the household detail views enforce with;
#   * queue-wide roles are exempt from the role condition, because
#     nsr_admin and GRM Officer already see and act on every case. A
#     rule that let them read a case but not be given it would be a
#     second visibility vocabulary, which is the defect this module's
#     neighbours were written to remove.
#
# A grievance about no household has no geography, so geography cannot
# decide it — the scope condition does not apply, exactly as
# visibility.visible_grievances treats the same rows.


def tier_rule(tier: str):
    """The active GrmTierRule for `tier`.

    No fallback: an unconfigured tier raises. A default here would mean
    the ladder silently reverting to whatever this module last believed,
    which is how the hardcoded copy went unnoticed.
    """
    from .models import GrmTierRule

    rule = GrmTierRule.objects.filter(tier=tier, is_active=True).first()
    if rule is None:
        raise IneligibleAssignee(
            f"no active GRM tier rule for {tier!r} — the escalation "
            "ladder is not configured",
        )
    return rule


def _queue_wide_q() -> Q:
    from .visibility import QUEUE_WIDE_ROLES

    return Q(groups__name__in=QUEUE_WIDE_ROLES)


def candidates(*, tier: str, household_id: str = ""):
    """Active users who may be given a case at `tier` about
    `household_id`, as a queryset ordered by username."""
    from apps.security.abac import user_can_access_household

    rule = tier_rule(tier)
    qs = (
        get_user_model().objects
        .filter(is_active=True)
        .filter(Q(groups__name=rule.required_role) | _queue_wide_q()
                | Q(is_superuser=True))
        .distinct()
        .prefetch_related("groups")
        .order_by("username")
    )
    if not household_id:
        return qs
    # Scope is per-user and not expressible as a join here (OperatorScope
    # resolves through effective() and a wildcard short-circuit), so it
    # is applied in Python over an already-narrow list.
    keep = [u.pk for u in qs if user_can_access_household(u, household_id)]
    return qs.filter(pk__in=keep)


def check(user, *, tier: str, household_id: str = "") -> None:
    """Raise IneligibleAssignee unless `user` may carry this case.

    The server-side half of the picker. A picker that offers the right
    names is a convenience; this is the rule.
    """
    from apps.security.abac import user_can_access_household
    from .visibility import QUEUE_WIDE_ROLES

    rule = tier_rule(tier)
    roles = set(user.groups.values_list("name", flat=True))
    carries_queue = bool(roles & set(QUEUE_WIDE_ROLES)) or user.is_superuser
    if not carries_queue and rule.required_role not in roles:
        raise IneligibleAssignee(
            f"{user.username!r} does not hold {rule.required_role!r}, the "
            f"role that carries {tier} cases",
        )
    if household_id and not user_can_access_household(user, household_id):
        raise IneligibleAssignee(
            f"{user.username!r} has no access to the household this case "
            "is about — assigning it would give them work they cannot open",
        )


def resolve_for(username: str, *, tier: str, household_id: str = ""):
    """resolve() plus the eligibility rule, in the order the operator
    would hit them: does this person exist, then may they have this."""
    user = resolve(username)
    check(user, tier=tier, household_id=household_id)
    return user
