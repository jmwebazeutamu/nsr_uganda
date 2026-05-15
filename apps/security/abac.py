"""ABAC geographic-scope enforcement.

SAD §8.2: "Attribute-based scope enforced by parish/sub-county/district
/region tag on the user account. ABAC policies evaluated at every read."

Sprint 2 enforces visibility at the **sub_region** level using the
denormalised partition key from ADR-0005. Finer-grained levels
(district / parish / village) are modelled by OperatorScope but the
matching path lives here once the relevant column is added to the row.

Fail-closed:
- Anonymous user → no rows visible.
- Authenticated user with no active scopes → no rows visible.
- Superuser bypass (Django staff admin pattern).
"""

from __future__ import annotations

from django.db.models import Q

from .models import OperatorScope, ScopeLevel


def scope_q_for_field(user, field: str = "sub_region_code") -> Q:
    """Return a Q expression filtering rows whose <field> matches one of
    the user's active sub_region scopes.

    `field` is a Django ORM lookup path on the model being queried. For
    Household / Member it's the default 'sub_region_code'; for Referral
    / ProgrammeEnrolment it's 'household__sub_region_code'; for any
    model that lacks a direct sub_region attribute the path walks the
    relation. The caller declares the path via
    ScopedQuerysetMixin.scope_field_path.

    Fail-closed:
    - Anonymous user -> Q(pk__in=[]) (no rows visible).
    - Authenticated user with no active scopes -> Q(pk__in=[]).
    - Superuser -> ~Q(pk__in=[]) (all rows visible).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    if getattr(user, "is_superuser", False):
        return ~Q(pk__in=[])
    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", "scope_code")
    )
    if not scopes:
        return Q(pk__in=[])
    q = Q(pk__in=[])
    for level, code in scopes:
        if level == ScopeLevel.NATIONAL:
            return ~Q(pk__in=[])
        if level == ScopeLevel.SUB_REGION and code:
            q |= Q(**{field: code})
        # district/parish/village/region levels are modelled but require
        # the denormalised matching column on the row; deferred to a
        # follow-up when the next set of denormalised codes lands.
    return q


def household_scope_q(user) -> Q:
    """Back-compat alias for the original Household-shaped helper."""
    return scope_q_for_field(user, "sub_region_code")


class ScopedQuerysetMixin:
    """Apply to ViewSets serving personal data so reads are scoped to
    the operator's geography. Use AFTER AuditReadMixin in the MRO so
    audit emit() still sees the request user.

    Override `scope_field_path` per viewset when the row's sub-region
    pointer isn't a direct column. Examples:
        scope_field_path = "sub_region_code"             # Household, Member
        scope_field_path = "household__sub_region_code"  # Referral, Enrolment
    """

    scope_field_path = "sub_region_code"

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(scope_q_for_field(self.request.user, self.scope_field_path))
