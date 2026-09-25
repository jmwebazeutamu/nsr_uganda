"""Who may see a grievance. One definition.

There were two, and they disagreed. The GRM list viewset asked
`_is_grm_officer()` — Django's `is_superuser` flag, or membership of a
group literally named "GRM Officer" — and gave anyone else only the
grievances they were assigned. The home dashboard counted the same rows
through the registry's normal ABAC scope, where a national OperatorScope
means "everything".

So an `nsr_admin` with a national scope, which is what a Super Admin
account actually looks like here, saw "5 Grievances open" on the
dashboard and an empty workbench. Neither number was wrong for the rule
that produced it; there should not have been two rules.

This module is the rule. It reuses `scope_q_for_field`, the same helper
Household and Member enforce with, so:

  * a superuser or a national scope matches every row;
  * a district / parish / village scope matches rows in those units;
  * no active scope matches nothing — fail-closed, deliberately.

Two grants sit beside the geographic one:

  * **GRM Officer**, the role whose job is the whole queue. Kept as it
    was, now read from the role catalogue rather than only a group name.
  * **Ownership** — the grievance is assigned to you, or you hold an
    open task on it. Without this an operator assigned a case outside
    their own area could not open the thing they were told to work on.
    It grants access to a specific row someone deliberately gave them,
    never to a class of rows, so it widens nothing by scope.

A grievance about no household has no geography, and geography cannot
decide it. Those are visible to the officers and to whoever owns them.
"""

from __future__ import annotations

from django.db.models import Q

from apps.security.abac import scope_q_for_field

from .models import TaskStatus

GRM_OFFICER_GROUP = "GRM Officer"

# Roles that carry the whole queue rather than a geographic slice.
# Named from the ADR-0028 catalogue, not invented here.
QUEUE_WIDE_ROLES = ("nsr_admin", "GRM Officer", "grm_officer")


def sees_every_grievance(user) -> bool:
    """True for the accounts whose job is the queue itself.

    Superusers, and the roles that administer the registry or run the
    GRM. `is_superuser` alone was the old test, which is why an
    `nsr_admin` was treated as an ordinary operator.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=QUEUE_WIDE_ROLES).exists()


def owned_q(user) -> Q:
    """Rows this user was personally given."""
    username = getattr(user, "username", "") or ""
    if not username:
        return Q(pk__in=[])
    return Q(assigned_to=username) | Q(
        tasks__assigned_to=username,
        tasks__status__in=[TaskStatus.OPEN, TaskStatus.IN_PROGRESS],
    )


def visible_grievances(user, queryset=None):
    """The grievances `user` may see, for lists AND for counts.

    Every surface that shows a number about grievances calls this — the
    workbench list, the home dashboard tile, the sidebar badge, the "in
    scope" label — so the numbers cannot disagree again.
    """
    from .models import Grievance

    qs = Grievance.objects.all() if queryset is None else queryset
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if sees_every_grievance(user):
        return qs

    # scope_q_for_field is fail-closed: no active scope yields
    # Q(pk__in=[]), so an unscoped operator sees only what they own.
    in_scope = scope_q_for_field(user, "sub_region_code")
    return qs.filter(in_scope | owned_q(user)).distinct()


# What a grievance will accept next, from the state machine.
#
# The console offered "Assign to me" on a closed case and the server
# refused it. Derived here from the same statuses the service guards
# check, so the buttons and the guards cannot drift — the UPD API
# already serves `allowed_actions` for the same reason.
_ASSIGNABLE = ("open", "in_progress", "escalated")
_ESCALATABLE = ("open", "in_progress", "escalated")
_RESOLVABLE = ("open", "in_progress", "escalated")
# create_task refuses RESOLVED and CLOSED, so a case accepts a task in
# every other state. Listed here because the console was deriving it
# from `status` itself, which is a second copy of this file.
_TASKABLE = ("open", "in_progress", "escalated")


def allowed_actions(grievance) -> list[str]:
    """The transitions this grievance will currently accept.

    Status only. Whether the CALLER may perform them is a separate
    question, answered by the role and scope checks on each action —
    this says what the case is ready for, not who may do it.
    """
    status = grievance.status
    if status == "closed":
        # A closed case is read-only. Not "closed plus a thread that
        # keeps growing": the closing narrative is the last word, and
        # new information about a settled case is a new case.
        return []
    actions = ["comment"]
    if status in _ASSIGNABLE:
        actions.append("assign")
    if status in _TASKABLE:
        actions.append("add_task")
    if status in _ESCALATABLE and grievance.tier != "l4_nsr_unit":
        actions.append("escalate")
    if status in _RESOLVABLE and not grievance.tasks.exclude(
        status="closed",
    ).exists():
        actions.append("resolve")
    if status == "resolved":
        actions.append("close")
    # No "reopen". The SAD does not mention re-opening a grievance at
    # all — not permitted, not forbidden, absent. Turning a closed,
    # audited case back into a live one raises questions the
    # architecture has not answered: whether the SLA clock restarts,
    # whether it needs approval, whether the reporter is told. Inventing
    # answers here would put a lifecycle transition into the registry
    # that nobody designed. Raised as an open item instead.
    if grievance.category == "data_correction" and grievance.household_id \
            and not grievance.linked_change_request_id:
        # Already linked means there is nothing left to open — the
        # service refuses a second one, and the console offering it
        # anyway is how a button comes to exist that only ever errors.
        actions.append("open_change_request")
    return actions
