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
from apps.reference_data.services import resolve_canonical_code
from apps.security.audit import emit as emit_audit

from .models import ProgrammeEnrolment


class EnrolmentEligibilityError(Exception):
    """A programme cannot enrol the submitted household selection."""

    def __init__(
        self, detail: str, *, code: str = "ineligible", dependencies=None,
        rejections=None,
    ):
        super().__init__(detail)
        self.code = code
        self.dependencies = list(dependencies or [])
        # Return policy reasons only: do not disclose household attributes
        # through a failed batch request.
        self.rejections = list(rejections or [])


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

    Composition codes have no registry-owned household predicate yet.
    PMT and sex codes are resolved separately through the active ChoiceList's
    ``canonical_code`` contract. Failing closed prevents a local
    approximation from becoming a second eligibility policy.
    """
    dependencies: list[str] = []
    if programme.composition_flags:
        dependencies.append("programme_composition_flag → canonical household predicate mapping")
    return dependencies


def _resolved_codes(list_name: str, configured_codes, dependency: str) -> list[str]:
    """Resolve configured choices to canonical values from Reference Data."""
    unresolved = []
    resolved = []
    for configured_code in configured_codes:
        found, canonical_code = resolve_canonical_code(list_name, configured_code)
        if not found or canonical_code is None:
            unresolved.append(str(configured_code))
        else:
            resolved.append(canonical_code)
    if unresolved:
        raise EnrolmentEligibilityError(
            "Programme eligibility cannot be resolved until its schema bindings are configured.",
            code="schema_dependency",
            dependencies=[f"{dependency}: {', '.join(unresolved)}"],
        )
    return resolved


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

    # Programme option codes are only UI/configuration identifiers. Resolve
    # them through the active Reference Data contract before filtering the
    # canonical PMT result and canonical household-head sex field.
    pmt_bands = _resolved_codes(
        "programme_pmt_band", programme.pmt_bands,
        "programme_pmt_band → canonical PMT band mapping",
    ) if programme.pmt_bands else []
    sex_codes = _resolved_codes(
        "programme_sex_filter", [programme.sex_filter],
        "programme_sex_filter → canonical household-head predicate mapping",
    ) if programme.sex_filter else []

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
    if pmt_bands:
        qs = qs.filter(current_vulnerability_band__in=pmt_bands)
    # The empty canonical code is the registry-owned meaning of an
    # unrestricted option; no local `any` sentinel exists in this policy.
    restricted_sex_codes = [code for code in sex_codes if code]
    if restricted_sex_codes:
        qs = qs.filter(head_member__sex__in=restricted_sex_codes)
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

    # Lock the programme before evaluating its status, DSA and saved scope.
    # A configuration change cannot race this batch between validation and
    # insertion.
    programme = Programme.objects.select_for_update().get(pk=programme.pk)
    existing_ids = {
        str(value) for value in ProgrammeEnrolment.objects.select_for_update()
        .filter(programme=programme, household_id__in=requested_ids)
        .values_list("household_id", flat=True)
    }
    eligible = list(eligible_household_rows(programme, household_ids=requested_ids))
    eligible_ids = {str(household.id) for household in eligible}
    available_ids = {
        str(value) for value in Household.objects.filter(
            id__in=requested_ids, is_deleted=False,
        ).values_list("id", flat=True)
    }
    rejections = []
    for household_id in requested_ids:
        if household_id not in available_ids:
            rejections.append({"household_id": household_id, "code": "not_available",
                               "reason": "Household does not exist or is no longer available."})
        elif household_id in existing_ids:
            rejections.append({"household_id": household_id, "code": "already_enrolled",
                               "reason": "Household is already enrolled in this programme."})
        elif household_id not in eligible_ids:
            rejections.append({"household_id": household_id, "code": "not_eligible",
                               "reason": "Household is outside saved programme geography or does not meet its configured eligibility."})
    if rejections:
        raise EnrolmentEligibilityError(
            "No households were enrolled because one or more selected households are invalid.",
            code="selection_ineligible",
            rejections=rejections,
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
    emit_audit(
        "create", "programme_enrolment_batch", str(programme.id), actor=actor,
        reason=f"direct enrolment batch created {len(created)} enrolment(s)",
        field_changes={
            "programme_id": str(programme.id),
            "household_ids": [str(enrolment.household_id) for enrolment in created],
            "created_count": len(created),
        },
    )
    return created
