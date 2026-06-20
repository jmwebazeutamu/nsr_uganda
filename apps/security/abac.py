"""ABAC geographic-scope enforcement.

SAD §8.2: "Attribute-based scope enforced by parish/sub-county/district
/region tag on the user account. ABAC policies evaluated at every read."

Enforcement is multi-level (ADR-0026): every OperatorScope level —
region / sub_region / district / sub_county / parish / village — resolves
against the matching Household column (sub_region uses the ADR-0005
denormalised partition key; the rest go through the level FK's `code`).
Household denormalises every UBOS level as an FK, so a coarse scope
contains its finer units automatically. `national` is the wildcard.

Fail-closed:
- Anonymous user → no rows visible.
- Authenticated user with no active scopes → no rows visible.
- Superuser bypass (Django staff admin pattern).
"""

from __future__ import annotations

from django.db.models import Q

from .models import OperatorScope, ScopeLevel

# Denormalised sub_region partition column (ADR-0005). The mixin's
# scope_field_path is this column optionally prefixed by a relation
# (e.g. "household__sub_region_code"); we derive that prefix and apply
# it to every level's column so one declaration covers all granularities.
_SUB_REGION_DENORM = "sub_region_code"

# ScopeLevel -> the Household column (relative to Household) that carries
# that geographic unit's code. Household denormalises every UBOS level as
# an FK, so a coarse scope (district) automatically contains its finer
# units — no hierarchy walk needed. sub_region uses the denormalised
# partition column; the rest go through the FK's `code`.
_LEVEL_FIELD: dict[str, str] = {
    ScopeLevel.REGION: "region__code",
    ScopeLevel.SUB_REGION: _SUB_REGION_DENORM,
    ScopeLevel.DISTRICT: "district__code",
    ScopeLevel.SUB_COUNTY: "sub_county__code",
    ScopeLevel.PARISH: "parish__code",
    ScopeLevel.VILLAGE: "village__code",
}


def _relation_prefix(field: str) -> str:
    """Derive the relation prefix from a scope_field_path.

    "sub_region_code" -> "" (row is Household-shaped);
    "household__sub_region_code" -> "household__" (row reaches geography
    through a Household FK). The prefix is prepended to every level's
    column so finer-grained scopes resolve through the same relation.
    """
    if field.endswith(_SUB_REGION_DENORM):
        return field[: -len(_SUB_REGION_DENORM)]
    return ""


def scope_q_for_field(user, field: str = "sub_region_code") -> Q:
    """Return a Q filtering rows to the operator's geographic scope, at
    whatever granularity each active OperatorScope declares
    (region / sub_region / district / sub_county / parish / village).

    `field` is the sub_region partition column on the model being
    queried — "sub_region_code" for Household/Member, or a relation path
    like "household__sub_region_code" for Referral / ProgrammeEnrolment /
    PMTResult. We derive the relation prefix from it and match each scope
    against the corresponding level column (containment is automatic
    because Household denormalises every level as an FK). The caller
    declares the path via ScopedQuerysetMixin.scope_field_path.

    Fail-closed:
    - Anonymous user -> Q(pk__in=[]) (no rows visible).
    - Authenticated user with no active scopes -> Q(pk__in=[]).
    - Authenticated user whose only scopes are non-geographic (PARTNER)
      -> Q(pk__in=[]) (this resolver is geographic; partner visibility
      is handled by PartnerScopedQuerysetMixin).
    - National scope or superuser -> ~Q(pk__in=[]) (all rows visible).
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
    prefix = _relation_prefix(field)
    q = Q(pk__in=[])
    for level, code in scopes:
        if level == ScopeLevel.NATIONAL:
            return ~Q(pk__in=[])
        rel = _LEVEL_FIELD.get(level)
        if rel and code:
            q |= Q(**{f"{prefix}{rel}": code})
    return q


def household_scope_q(user) -> Q:
    """Back-compat alias for the original Household-shaped helper."""
    return scope_q_for_field(user, "sub_region_code")


def user_can_access_household(user, household_id) -> bool:
    """True if the operator's geographic scope covers this household
    (or the user is national/superuser). For single-entity views that
    take a household id by URL/param rather than listing a queryset —
    they call this to decide 404-vs-serve. One indexed query; no full
    scope materialisation. Empty/anonymous/partner-only scope -> False.
    """
    if not household_id:
        return False
    from apps.data_management.models import Household
    return Household.objects.filter(
        Q(pk=household_id) & scope_q_for_field(user, _SUB_REGION_DENORM)
    ).exists()


def user_can_access_member(user, member_id) -> bool:
    """True if the operator's scope covers the member's household (or
    national/superuser). Single-entity counterpart for member-id views."""
    if not member_id:
        return False
    from apps.data_management.models import Member
    return Member.objects.filter(
        Q(pk=member_id) & scope_q_for_field(user, f"household__{_SUB_REGION_DENORM}")
    ).exists()


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


def _scoped_household_ids(user) -> list[str] | None:
    """Resolve a user to the Household PKs their active scopes cover,
    across ALL granularities. Returns None for 'visible to all'
    (superuser or national) and [] for fail-closed. Used by the
    ID-subquery mixins (Submission/StageRecord, MatchPair, ChangeRequest)
    which can't express geography as a single column on their own row.

    Built on top of scope_q_for_field so the multi-level semantics live
    in exactly one place.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None
    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", flat=True)
    )
    if not scopes:
        return []
    if any(level == ScopeLevel.NATIONAL for level in scopes):
        return None
    from apps.data_management.models import Household
    return list(
        Household.objects.filter(scope_q_for_field(user, _SUB_REGION_DENORM))
        .values_list("id", flat=True)
    )


def _scoped_codes(user) -> list[str] | None:
    """Resolve a user to the list of sub_region_codes their active
    scopes cover. Returns None as a sentinel for 'visible to all' (i.e.,
    superuser or national scope) and [] for fail-closed.

    NOTE sub_region-granularity only — retained for the reporting
    aggregates that GROUP BY sub_region_code. Row-level personal-data
    enforcement goes through scope_q_for_field / _scoped_household_ids,
    which are multi-level. See ADR-0026."""
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
        household_ids = _scoped_household_ids(self.request.user)
        if household_ids is None:
            return ~Q(pk__in=[])  # wildcard
        if not household_ids:
            return Q(pk__in=[])
        return Q(**{f"{self.scope_field_path}__in": household_ids})


def _scoped_partner_codes(user) -> list[str] | None:
    """Partner-scope counterpart to _scoped_codes.

    Same sentinel convention: None means wildcard (superuser or
    national scope), [] means fail-closed, otherwise the list of
    Partner.code values the operator is affiliated with.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superuser", False):
        return None
    scopes = list(
        OperatorScope.objects.filter(user=user, active=True)
        .values_list("scope_level", "scope_code")
    )
    if not scopes:
        return []
    if any(level == ScopeLevel.NATIONAL for level, _ in scopes):
        return None
    return [c for level, c in scopes if level == ScopeLevel.PARTNER and c]


class PartnerScopedQuerysetMixin(ScopedQuerysetMixin):
    """ABAC variant for API-DRS rows. Partner-affiliated users see only
    rows tied to their Partner; NSR Unit (national) and superusers see
    all. Geographic scope is ignored — partner visibility is
    org-affiliation, not geography.

    `partner_id_field` is the lookup path from the model to Partner.pk:
        DataRequest   -> 'dsa__partner_id'      (default)
        DataSharingAgreement -> 'partner_id'
        Partner       -> 'id'

    Layer AFTER AuditReadMixin in MRO so audit emit() still sees the
    request user before scope filtering.
    """

    partner_id_field: str = "dsa__partner_id"

    def _scope_q(self) -> Q:
        codes = _scoped_partner_codes(self.request.user)
        if codes is None:
            return ~Q(pk__in=[])  # wildcard
        if not codes:
            return Q(pk__in=[])
        # ADR-0013: canonical Partner lives in apps.partners.
        from apps.partners.models import Partner
        partner_ids = list(
            Partner.objects.filter(code__in=codes).values_list("id", flat=True),
        )
        return Q(**{f"{self.partner_id_field}__in": partner_ids})


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
        household_ids = _scoped_household_ids(self.request.user)
        if household_ids is None:
            return ~Q(pk__in=[])  # wildcard
        if not household_ids:
            return Q(pk__in=[])

        from apps.data_management.models import Member
        member_ids = list(
            Member.objects.filter(household_id__in=household_ids)
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
        household_ids = _scoped_household_ids(self.request.user)
        if household_ids is None:
            return ~Q(pk__in=[])
        if not household_ids:
            return Q(pk__in=[])

        from apps.data_management.models import Member
        member_ids = list(
            Member.objects.filter(household_id__in=household_ids)
            .values_list("id", flat=True)
        )
        return (
            Q(entity_type="household", entity_id__in=household_ids)
            | Q(entity_type="member", entity_id__in=member_ids)
        )
