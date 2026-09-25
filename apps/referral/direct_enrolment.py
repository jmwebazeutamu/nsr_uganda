"""Canonical direct household-enrolment policy.

This module deliberately owns no eligibility configuration.  It evaluates the
programme, DSA and household records that already own those facts, then writes
the existing ``ProgrammeEnrolment`` relationship.  A programme configuration
whose choice-list semantics have not been bound to canonical data is refused
instead of guessed at.
"""

from __future__ import annotations

from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.data_management.models import Household
from apps.partners.models import Programme
from apps.partners.services.programme_scope import validated_programme_geography
from apps.security.audit import emit as emit_audit

from .models import ProgrammeEnrolment


class EnrolmentEligibilityError(Exception):
    """A programme cannot enrol the submitted household selection."""

    def __init__(self, detail: str, *, code: str = "ineligible", dependencies=None):
        super().__init__(detail)
        self.code = code
        self.dependencies = list(dependencies or [])


def _dsa_is_effective(dsa) -> bool:
    today = timezone.localdate()
    return (
        dsa.status == "active"
        and (dsa.effective_from is None or dsa.effective_from <= today)
        and (dsa.effective_to is None or today < dsa.effective_to)
    )


def _scope_q(units) -> Q:
    """A household is in scope when it matches a saved programme unit.

    Household's geography-code columns are its canonical, indexed projection
    of the UBOS hierarchy.  The mapping is owned by Household so the policy
    does not duplicate the geography ladder.
    """
    query = Q(pk__in=[])
    for unit in units:
        field = Household.GEO_CODE_FIELDS.get(unit.level)
        if field is None:
            raise EnrolmentEligibilityError(
                f"Geographic level {unit.level!r} is not available on the canonical Household model.",
                code="schema_dependency",
                dependencies=[f"Household geography field for {unit.level}"],
            )
        query |= Q(**{field: unit.code})
    return query


def schema_dependencies(programme: Programme) -> list[str]:
    """Return configured rules without an executable registry binding.

    PMT band, composition and programme-sex codes are display ChoiceLists at
    present.  They have no registry-owned mapping to a PMT band or canonical
    questionnaire predicate.  Failing closed prevents a local approximation
    from becoming a second eligibility policy.
    """
    dependencies: list[str] = []
    if programme.pmt_bands:
        dependencies.append("programme_pmt_band → canonical PMT band mapping")
    if programme.composition_flags:
        dependencies.append("programme_composition_flag → canonical household predicate mapping")
    if programme.sex_filter:
        dependencies.append("programme_sex_filter → canonical household-head predicate mapping")
    return dependencies


def programme_eligibility_queryset(programme: Programme):
    """Resolve eligible households from the canonical Programme/DSA contract."""
    if programme.status != "active":
        raise EnrolmentEligibilityError(
            f"Programme {programme.code or programme.id} is not active.", code="programme_inactive",
        )
    if programme.dsa_id is None:
        raise EnrolmentEligibilityError(
            "Programme has no governing Data Sharing Agreement.", code="dsa_missing",
        )
    dsa = programme.dsa
    if not _dsa_is_effective(dsa):
        raise EnrolmentEligibilityError(
            f"DSA {dsa.reference} is not active and effective for enrolment.", code="dsa_inactive",
        )
    if programme.unit_of_enrolment != "household":
        raise EnrolmentEligibilityError(
            "This workflow enrols households only; the programme's unit of enrolment is not household.",
            code="unit_not_household",
        )
    dependencies = schema_dependencies(programme)
    if dependencies:
        raise EnrolmentEligibilityError(
            "Programme eligibility cannot be resolved until its schema bindings are configured.",
            code="schema_dependency", dependencies=dependencies,
        )

    units = list(programme.geographic_units.all())
    try:
        # Revalidate the saved programme geography against the active DSA at
        # every read/write boundary; no UI cache or historic fixture decides.
        units = validated_programme_geography(dsa, units)
    except ValueError as exc:
        raise EnrolmentEligibilityError(str(exc), code="geography_invalid") from exc
    if dsa.geographic_scope.exists() and not units:
        raise EnrolmentEligibilityError(
            f"Programme has no resolved geography under limited DSA {dsa.reference}.",
            code="geography_missing",
        )

    qs = Household.objects.filter(is_deleted=False)
    if units:
        qs = qs.filter(_scope_q(units))
    if programme.age_min is not None:
        qs = qs.filter(head_member__age_years__gte=programme.age_min)
    if programme.age_max is not None:
        qs = qs.filter(head_member__age_years__lte=programme.age_max)
    return qs.select_related("head_member", "region", "sub_region", "district")


def eligible_household_rows(programme: Programme, *, household_ids=None):
    """Return canonical eligible households, optionally restricted to IDs."""
    qs = programme_eligibility_queryset(programme)
    if household_ids is not None:
        qs = qs.filter(id__in=household_ids)
    return qs.order_by("id")


@transaction.atomic
def enrol_households_directly(*, programme: Programme, household_ids, actor: str,
                              effective_date: date | None = None) -> list[ProgrammeEnrolment]:
    """Validate the complete selection then create enrolments atomically."""
    requested_ids = list(dict.fromkeys(str(value) for value in household_ids if value))
    if not requested_ids:
        raise EnrolmentEligibilityError("Select at least one household.", code="selection_empty")

    eligible = list(eligible_household_rows(programme, household_ids=requested_ids))
    eligible_ids = {str(household.id) for household in eligible}
    rejected = sorted(set(requested_ids) - eligible_ids)
    if rejected:
        raise EnrolmentEligibilityError(
            "Selected household(s) are outside the programme's current eligibility scope: "
            + ", ".join(rejected),
            code="selection_ineligible",
        )

    existing = set(
        ProgrammeEnrolment.objects.select_for_update()
        .filter(programme=programme, household_id__in=requested_ids)
        .exclude(status="exited")
        .values_list("household_id", flat=True),
    )
    if existing:
        raise EnrolmentEligibilityError(
            "Selected household(s) already have a live enrolment in this programme: "
            + ", ".join(sorted(str(value) for value in existing)),
            code="already_enrolled",
        )

    enrolled_on = effective_date or timezone.localdate()
    try:
        created = ProgrammeEnrolment.objects.bulk_create([
            ProgrammeEnrolment(
                programme=programme, household=household, status="active",
                effective_date=enrolled_on,
            )
            for household in eligible
        ])
    except IntegrityError as exc:
        raise EnrolmentEligibilityError(
            "An enrolment changed concurrently; refresh the eligible households and try again.",
            code="concurrent_change",
        ) from exc
    for enrolment in created:
        emit_audit(
            "create", "programme_enrolment", enrolment.id, actor=actor,
            reason=f"direct household enrolment in {programme.code or programme.id}",
            field_changes={"programme_id": str(programme.id), "household_id": str(enrolment.household_id)},
        )
    return created
