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


def household_scope_q(user) -> Q:
    """Return a Q expression filtering Household/Member rows by the
    operator's active scopes. Same expression works for any model that
    carries a sub_region_code column (Household and Member both do, per
    US-S1-007)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    if getattr(user, "is_superuser", False):
        return ~Q(pk__in=[])  # vacuously True — all rows visible
    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", "scope_code")
    )
    if not scopes:
        return Q(pk__in=[])  # fail-closed
    q = Q(pk__in=[])  # OR-of-nothing starting point
    for level, code in scopes:
        if level == ScopeLevel.NATIONAL:
            return ~Q(pk__in=[])
        if level == ScopeLevel.SUB_REGION and code:
            q |= Q(sub_region_code=code)
        # district/parish/village/region levels are modelled but require
        # the denormalised matching column on the row; deferred to
        # Sprint 2.5 when the next set of denormalised codes lands.
    return q


class ScopedQuerysetMixin:
    """Apply to ViewSets serving personal data so reads are scoped to
    the operator's geography. Use AFTER AuditReadMixin in the MRO so
    audit emit() still sees the request user."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(household_scope_q(self.request.user))
