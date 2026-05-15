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
        return qs.filter(self._scope_q())

    def _scope_q(self) -> Q:
        return scope_q_for_field(self.request.user, self.scope_field_path)


def _scoped_codes(user) -> list[str] | None:
    """Resolve a user to the list of sub_region_codes their active
    scopes cover. Returns None as a sentinel for 'visible to all' (i.e.,
    superuser or national scope) and [] for fail-closed."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None  # superuser sees everything
    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", "scope_code")
    )
    if not scopes:
        return []  # fail-closed
    if any(level == ScopeLevel.NATIONAL for level, _ in scopes):
        return None  # wildcard
    return [c for level, c in scopes if level == ScopeLevel.SUB_REGION and c]


class HouseholdIdScopedQuerysetMixin(ScopedQuerysetMixin):
    """ABAC variant for models that hold the household reference as a
    CharField (`household_id`, `provisional_registry_id`) rather than a
    real Django FK to Household. Resolves the scoped households once
    and uses an IN subquery.

    Applies to:
    - Submission.provisional_registry_id (pre-promotion the household
      doesn't exist yet — those rows are invisible to scoped operators,
      which is correct: pre-promotion lives in DIH and is NSR-Unit-
      visibility only).
    - Grievance.household_id.
    - StageRecord.provisional_registry_id (same pre-promotion behaviour).
    """

    scope_field_path = "household_id"

    def _scope_q(self) -> Q:
        codes = _scoped_codes(self.request.user)
        if codes is None:
            return ~Q(pk__in=[])  # wildcard
        if not codes:
            return Q(pk__in=[])

        # Imported lazily so apps.security doesn't depend on
        # apps.data_management at module import (cycle safety).
        from apps.data_management.models import Household
        household_ids = list(
            Household.objects.filter(sub_region_code__in=codes)
            .values_list("id", flat=True)
        )
        return Q(**{f"{self.scope_field_path}__in": household_ids})


class MatchPairScopedQuerysetMixin(ScopedQuerysetMixin):
    """ABAC variant for MatchPair (DDUP).

    A pair is visible only when BOTH members fall within the operator's
    geographic scope. Single-end scoping would leak the opposing member's
    ID (and its existence) to an operator who has no authority over that
    geography — the dedup workbench reveals enough identifying detail
    that a one-sided rule would amount to a covert read of the other
    side. National / superuser short-circuits remain.
    """

    def _scope_q(self) -> Q:
        codes = _scoped_codes(self.request.user)
        if codes is None:
            return ~Q(pk__in=[])  # wildcard
        if not codes:
            return Q(pk__in=[])

        from apps.data_management.models import Member
        member_ids = list(
            Member.objects.filter(household__sub_region_code__in=codes)
            .values_list("id", flat=True)
        )
        return Q(record_a_id__in=member_ids) & Q(record_b_id__in=member_ids)


class ChangeRequestScopedQuerysetMixin(ScopedQuerysetMixin):
    """ABAC variant for ChangeRequest. The row carries (entity_type,
    entity_id) where entity_type ∈ {household, member}. We resolve the
    scope to the matching household IDs once and OR two clauses:

        Q(entity_type='household', entity_id__in=<household_ids>) |
        Q(entity_type='member',    entity_id__in=<member_ids_for_those_households>)

    so an operator scoped to sub-region X sees CRs that target either a
    household in X or a member of a household in X.
    """

    def _scope_q(self) -> Q:
        codes = _scoped_codes(self.request.user)
        if codes is None:
            return ~Q(pk__in=[])
        if not codes:
            return Q(pk__in=[])

        from apps.data_management.models import Household, Member
        household_ids = list(
            Household.objects.filter(sub_region_code__in=codes)
            .values_list("id", flat=True)
        )
        member_ids = list(
            Member.objects.filter(household_id__in=household_ids)
            .values_list("id", flat=True)
        )
        return (
            Q(entity_type="household", entity_id__in=household_ids)
            | Q(entity_type="member", entity_id__in=member_ids)
        )
