from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.security.abac import ScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin
from apps.security.pagination import MemberPagination

from .choice_field_map import (
    ASSET_FIELDS,
    COPING_FIELDS,
    CROP_FIELDS,
    DISABILITY_FIELDS,
    DWELLING_FIELDS,
    EDUCATION_FIELDS,
    EMPLOYMENT_FIELDS,
    FOOD_CONSUMPTION_FIELDS,
    FOOD_SECURITY_FIELDS,
    HEALTH_FIELDS,
    HOUSEHOLD_FIELDS,
    LIVELIHOOD_FIELDS,
    LIVESTOCK_FIELDS,
    MEMBER_FIELDS,
    SHOCK_FIELDS,
    UTILITIES_FIELDS,
    apply_payload_labels,
)
from .models import (
    AssetOwnership,
    CopingStrategy,
    Crop,
    Disability,
    Dwelling,
    Education,
    Employment,
    FoodConsumption,
    FoodSecurity,
    Health,
    Household,
    Livelihood,
    Livestock,
    Member,
    Shock,
    Utilities,
)


def _stage_for(household):
    """Cache the upstream StageRecord on the household instance so
    get_source_payload, get_source_payload_labels, and _intake_date
    share a single query. The attribute is set on the in-memory
    Household object; it does not persist."""
    cached = getattr(household, "_cached_stage", "__miss__")
    if cached != "__miss__":
        return cached
    from apps.ingestion_hub.models import StageRecord
    stage = (
        StageRecord.objects
        .filter(provisional_registry_id=household.id)
        .only("canonical_payload", "created_at")
        .first()
    )
    household._cached_stage = stage
    return stage


def _intake_date(household):
    """as_of date for label resolution on a Household. Falls back to
    Household.created_at (or today via the resolver) when no upstream
    StageRecord is available."""
    stage = _stage_for(household)
    src = stage or household
    ts = getattr(src, "created_at", None)
    return ts.date() if ts else None


def _attach_label_methodfields(serializer_cls, fmap):
    """Inject a SerializerMethodField for each entry in `fmap` onto
    `serializer_cls`. The fields are registered into
    `_declared_fields` so DRF's field-binding picks them up (post-
    class setattr alone doesn't trigger the SerializerMetaclass).
    Called at module import — the resulting fields are baked into
    Meta.fields below.
    """
    for field, (list_name, kind) in fmap.items():
        attr = f"{field}_label" if kind == "single" else f"{field}_labels"
        method_name = f"get_{attr}"

        def _make(field=field, kind=kind, list_name=list_name):
            def method(self, obj):
                from apps.reference_data.services import (
                    resolve_label,
                    resolve_labels,
                )
                as_of = _intake_date_for_obj(obj)
                resolver = resolve_label if kind == "single" else resolve_labels
                return resolver(
                    list_name,
                    getattr(obj, field),
                    as_of=as_of,
                    context={"entity_id": getattr(obj, "id", None), "field": field},
                )
            return method

        smf = serializers.SerializerMethodField(method_name=method_name)
        setattr(serializer_cls, attr, smf)
        # DRF's SerializerMetaclass froze `_declared_fields` at class
        # creation; mirror our setattr into it so build_field can
        # resolve the name.
        serializer_cls._declared_fields[attr] = smf
        setattr(serializer_cls, method_name, _make())


def _intake_date_for_obj(obj):
    """Member or Household both route to the same intake date —
    a member inherits its household's intake date."""
    hh = obj if isinstance(obj, Household) else getattr(obj, "household", None)
    if hh is None:
        return None
    return _intake_date(hh)


def _safe_reverse_o2o(parent, attr):
    """Read a reverse OneToOne accessor and return None when the related
    row doesn't exist. Django's descriptor raises ObjectDoesNotExist —
    we treat that as "no detail entity yet" rather than letting the
    serialiser crash."""
    try:
        return getattr(parent, attr)
    except Exception:  # noqa: BLE001 — incl. RelatedObjectDoesNotExist
        return None


class MemberSerializer(serializers.ModelSerializer):
    nin_value = serializers.SerializerMethodField()
    # US-S22-DE-08: per-Member detail entities nested read-only.
    # SerializerMethodField so a member without the child row
    # serialises as null instead of raising ObjectDoesNotExist.
    health = serializers.SerializerMethodField()
    disability = serializers.SerializerMethodField()
    education = serializers.SerializerMethodField()
    employment = serializers.SerializerMethodField()
    # US-005 — household location names so the Members list can render
    # a location chip without a follow-up fetch per row. select_related
    # on the viewset keeps these zero-query. Defaults to "" for any
    # row whose household FK chain is incomplete (shouldn't happen
    # against promoted households).
    household_sub_region_name = serializers.CharField(
        source="household.sub_region.name", read_only=True, default="",
    )
    household_district_name = serializers.CharField(
        source="household.district.name", read_only=True, default="",
    )
    household_parish_name = serializers.CharField(
        source="household.parish.name", read_only=True, default="",
    )
    household_village_name = serializers.CharField(
        source="household.village.name", read_only=True, default="",
    )
    household_pmt_band = serializers.CharField(
        source="household.current_vulnerability_band", read_only=True, default="",
    )

    class Meta:
        model = Member
        fields = (
            "id", "household", "line_number", "surname", "first_name", "other_name",
            "relationship_to_head", "relationship_to_head_label",
            "sex", "sex_label",
            "date_of_birth", "age_years",
            "marital_status", "marital_status_label",
            "nationality", "nationality_label",
            "residency_status", "residency_status_label",
            "birth_certificate_status", "birth_certificate_status_label",
            "nin_status", "nin_status_label",
            "nin_last4", "nin_value",
            "telephone_1", "telephone_2", "is_deleted", "merged_into",
            "health", "disability", "education", "employment",
            "household_sub_region_name", "household_district_name",
            "household_parish_name", "household_village_name",
            "household_pmt_band",
            "updated_at",
        )

    def get_nin_value(self, obj) -> str | None:
        """NIN plaintext is never serialised. nin_last4 + nin_status are
        the operator-facing surface."""
        return None

    def get_health(self, obj):
        h = _safe_reverse_o2o(obj, "health")
        return HealthSerializer(h).data if h else None

    def get_disability(self, obj):
        d = _safe_reverse_o2o(obj, "disability")
        return DisabilitySerializer(d).data if d else None

    def get_education(self, obj):
        e = _safe_reverse_o2o(obj, "education")
        return EducationSerializer(e).data if e else None

    def get_employment(self, obj):
        e = _safe_reverse_o2o(obj, "employment")
        return EmploymentSerializer(e).data if e else None


_attach_label_methodfields(MemberSerializer, MEMBER_FIELDS)


# ===========================================================================
# Detail-entity serializers (US-S22-DE-08)
#
# One ModelSerializer per detail entity from US-S22-DE-01. Each gets
# its <field>_label companions auto-attached via the choice_field_map
# entry per ADR-0010. They're nested read-only onto HouseholdSerializer
# and MemberSerializer below — the registry surface now exposes the
# socioeconomic detail tail without callers having to walk the
# StageRecord.canonical_payload by hand.
# ===========================================================================


class DwellingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dwelling
        fields = (
            "id", "tenure", "tenure_label",
            "dwelling_type", "dwelling_type_label",
            "total_rooms", "sleeping_rooms",
            "roof_material", "roof_material_label",
            "wall_material", "wall_material_label",
            "floor_material", "floor_material_label",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(DwellingSerializer, DWELLING_FIELDS)


class UtilitiesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Utilities
        fields = (
            "id", "cooking_fuel", "cooking_fuel_label",
            "lighting_energy", "lighting_energy_label",
            "drinking_water_source", "drinking_water_source_label",
            "toilet_facility", "toilet_facility_label",
            "toilet_shared", "households_sharing_toilet",
            "waste_disposal", "waste_disposal_label",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(UtilitiesSerializer, UTILITIES_FIELDS)


class LivelihoodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Livelihood
        fields = (
            "id", "main_livelihood", "main_livelihood_label",
            "crop_production_zone", "crop_production_zone_label",
            "livestock_zone", "livestock_zone_label",
            "agricultural_purpose", "agricultural_purpose_label",
            "land_ownership", "land_ownership_label",
            "land_hectares",
            "land_title", "land_title_label",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(LivelihoodSerializer, LIVELIHOOD_FIELDS)


class FoodSecuritySerializer(serializers.ModelSerializer):
    class Meta:
        model = FoodSecurity
        fields = (
            "id",
            "worried_food", "worried_food_label",
            "unhealthy_food", "unhealthy_food_label",
            "limited_variety", "limited_variety_label",
            "skipped_meal", "skipped_meal_label",
            "ate_less", "ate_less_label",
            "ran_out_food", "ran_out_food_label",
            "hungry_no_eat", "hungry_no_eat_label",
            "whole_day_no_eat", "whole_day_no_eat_label",
            "fies_raw_score",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(FoodSecuritySerializer, FOOD_SECURITY_FIELDS)


class FoodConsumptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FoodConsumption
        fields = (
            "id",
            "staples_days", "staples_source", "staples_source_label",
            "pulses_days", "pulses_source", "pulses_source_label",
            "dairy_days", "dairy_source", "dairy_source_label",
            "meat_days", "meat_source", "meat_source_label",
            "vegetables_days", "vegetables_source", "vegetables_source_label",
            "fruits_days", "fruits_source", "fruits_source_label",
            "oils_days", "oils_source", "oils_source_label",
            "sugar_days", "sugar_source", "sugar_source_label",
            "condiments_days", "condiments_source", "condiments_source_label",
            "fcs_score",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(FoodConsumptionSerializer, FOOD_CONSUMPTION_FIELDS)


class AssetOwnershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetOwnership
        fields = (
            "id", "asset_type", "asset_type_label", "count",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(AssetOwnershipSerializer, ASSET_FIELDS)


class CropSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crop
        fields = (
            "id", "crop_name", "crop_name_label", "rank_order",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(CropSerializer, CROP_FIELDS)


class LivestockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Livestock
        fields = (
            "id", "livestock_type", "livestock_type_label", "count",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(LivestockSerializer, LIVESTOCK_FIELDS)


class ShockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shock
        fields = (
            "id", "shock_type", "shock_type_label",
            "livelihoods_affected",
            "severity", "severity_label",
            "crops_severity_score", "livestock_severity_score",
            "labour_severity_score", "other_severity_score",
            "event_date",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(ShockSerializer, SHOCK_FIELDS)


class CopingStrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = CopingStrategy
        fields = (
            "id",
            "strategy_type", "strategy_type_label",
            "category",
            "frequency", "frequency_label",
            "used_flag",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(CopingStrategySerializer, COPING_FIELDS)


class HealthSerializer(serializers.ModelSerializer):
    # Chronic illness type list lives in the encrypted column —
    # surface via the explicit decoded list so callers don't see
    # the raw bytes. Plaintext HIV/TB codes never appear on the wire
    # except through this controlled accessor (DPPA 2019).
    chronic_illness_types = serializers.SerializerMethodField()

    class Meta:
        model = Health
        fields = (
            "id",
            "chronic_illness_flag", "chronic_illness_flag_label",
            "chronic_illness_types",
            "sub_region_code", "is_deleted", "updated_at",
        )

    def get_chronic_illness_types(self, obj) -> list[str]:
        return obj.get_chronic_illness_types()


_attach_label_methodfields(HealthSerializer, HEALTH_FIELDS)


class DisabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Disability
        fields = (
            "id",
            "seeing", "seeing_label",
            "hearing", "hearing_label",
            "walking", "walking_label",
            "memory", "memory_label",
            "selfcare", "selfcare_label",
            "communication", "communication_label",
            "wg_disability_flag",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(DisabilitySerializer, DISABILITY_FIELDS)


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = (
            "id",
            "literacy_status", "literacy_status_label",
            "ever_attended", "ever_attended_label",
            "never_attended_reason", "never_attended_reason_label",
            "highest_grade", "highest_grade_label",
            "currently_attending", "currently_attending_label",
            "why_stopped", "why_stopped_label",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(EducationSerializer, EDUCATION_FIELDS)


class EmploymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employment
        fields = (
            "id",
            "main_activity_last_30d", "main_activity_last_30d_label",
            "work_frequency", "work_frequency_label",
            "sector", "sector_label",
            "employment_status", "employment_status_label",
            "not_working_reason", "not_working_reason_label",
            "is_govt_programme_beneficiary", "is_govt_programme_beneficiary_label",
            "programmes_benefited",
            "currently_benefiting", "currently_benefiting_label",
            "made_savings", "made_savings_label",
            "savings_location", "savings_location_label",
            "sub_region_code", "is_deleted", "updated_at",
        )


_attach_label_methodfields(EmploymentSerializer, EMPLOYMENT_FIELDS)


class HouseholdSerializer(serializers.ModelSerializer):
    members = MemberSerializer(many=True, read_only=True)
    # Geo names so the React detail screen can render the address
    # chain without N+1 lookups against /geographic-units/. Codes
    # stay on the FK fields (region, sub_region, ...) for callers
    # that join programmatically; names are flat strings for display.
    region_name = serializers.CharField(source="region.name", read_only=True, default="")
    sub_region_name = serializers.CharField(source="sub_region.name", read_only=True, default="")
    district_name = serializers.CharField(source="district.name", read_only=True, default="")
    county_name = serializers.CharField(source="county.name", read_only=True, default="")
    sub_county_name = serializers.CharField(source="sub_county.name", read_only=True, default="")
    parish_name = serializers.CharField(source="parish.name", read_only=True, default="")
    village_name = serializers.CharField(source="village.name", read_only=True, default="")
    current_intake_source = serializers.CharField(read_only=True)
    # US-S22-DE-08: per-Household detail entities nested read-only.
    # The five one-to-ones use SerializerMethodField so a household
    # without the child row serialises as null rather than crashing.
    # The five repeat groups use the standard nested-many pattern;
    # they always exist as a (possibly empty) queryset.
    dwelling = serializers.SerializerMethodField()
    utilities = serializers.SerializerMethodField()
    livelihood = serializers.SerializerMethodField()
    food_security = serializers.SerializerMethodField()
    food_consumption = serializers.SerializerMethodField()
    assets = AssetOwnershipSerializer(many=True, read_only=True)
    crops = CropSerializer(many=True, read_only=True)
    livestock = LivestockSerializer(many=True, read_only=True)
    shocks = ShockSerializer(many=True, read_only=True)
    coping_strategies = CopingStrategySerializer(many=True, read_only=True)
    # US-S11-020 — surface the canonical_payload of the StageRecord
    # that promoted this household so the React detail screen can
    # render the questionnaire's housing / education / employment /
    # food-security / shocks blocks without inventing dedicated
    # detail tables. Returns null when no upstream StageRecord
    # exists (e.g., walk-in CAPI households whose payload wasn't
    # carried through the DIH pipeline).
    source_payload = serializers.SerializerMethodField()
    # US-S22-005d — parallel labels tree, computed against the
    # ChoiceList catalogue active at the intake date. Audit blob in
    # source_payload is bit-for-bit untouched.
    source_payload_labels = serializers.SerializerMethodField()

    class Meta:
        model = Household
        fields = (
            "id", "head_member", "region", "sub_region", "district",
            "county", "sub_county", "parish", "village",
            "region_name", "sub_region_name", "district_name",
            "county_name", "sub_county_name", "parish_name", "village_name",
            "urban_rural", "urban_rural_label",
            "enumeration_area", "household_number",
            "address_narrative",
            "gps_lat", "gps_lng", "gps_accuracy_m",
            "dwelling_tenure", "dwelling_tenure_label",
            "residence_status", "residence_status_label",
            "current_pmt_score", "current_vulnerability_band",
            "current_intake_source",
            "is_deleted", "created_at", "updated_at", "members",
            "source_payload", "source_payload_labels",
            # US-S22-DE-08 detail entities
            "dwelling", "utilities", "livelihood",
            "food_security", "food_consumption",
            "assets", "crops", "livestock",
            "shocks", "coping_strategies",
        )

    def get_dwelling(self, obj):
        d = _safe_reverse_o2o(obj, "dwelling")
        return DwellingSerializer(d).data if d else None

    def get_utilities(self, obj):
        u = _safe_reverse_o2o(obj, "utilities")
        return UtilitiesSerializer(u).data if u else None

    def get_livelihood(self, obj):
        liv = _safe_reverse_o2o(obj, "livelihood")
        return LivelihoodSerializer(liv).data if liv else None

    def get_food_security(self, obj):
        fs = _safe_reverse_o2o(obj, "food_security")
        return FoodSecuritySerializer(fs).data if fs else None

    def get_food_consumption(self, obj):
        fc = _safe_reverse_o2o(obj, "food_consumption")
        return FoodConsumptionSerializer(fc).data if fc else None

    def get_source_payload(self, obj) -> dict | None:
        """Joins back to the StageRecord that promoted this
        household. provisional_registry_id matches Household.id by
        construction (AC-DIH-PROMOTE-ATOMIC — same ULID is reused
        on promotion). Returns the canonical_payload JSON or None.
        Caches the StageRecord on the household instance so
        get_source_payload_labels and _intake_date share the same
        query (US-S22-005j)."""
        stage = _stage_for(obj)
        return stage.canonical_payload if stage else None

    def get_source_payload_labels(self, obj) -> dict:
        """Walk source_payload via choice_field_map.PAYLOAD_FIELDS and
        emit a parallel tree of resolved labels at the intake date.
        Never mutates source_payload (ADR-0010 §2)."""
        payload = self.get_source_payload(obj)
        if not payload:
            return {}
        from apps.reference_data.services import resolve_label
        as_of = _intake_date(obj)
        return apply_payload_labels(payload, resolve_label, as_of=as_of)


_attach_label_methodfields(HouseholdSerializer, HOUSEHOLD_FIELDS)


# --- Registry browse filter helpers (US-005) --------------------------------
#
# The Registry browse screens (Households + Members + Member Detail) need
# server-side filters that round-trip through query params, plus aggregate
# endpoints for the KPI strips. django-filter isn't installed (per the
# project's testing memo) so each filter is applied manually here. The
# helpers are module-level so the aggregate endpoints can reuse the same
# pipeline as the list endpoints.

# Age-band bucket → inclusive (min, max) over Member.age_years. None means
# "no bound on that end". Matches the seven bands the prototype renders.
_AGE_BANDS = {
    "<5":    (None, 4),
    "5-9":   (5, 9),
    "10-14": (10, 14),
    "15-19": (15, 19),
    "20-29": (20, 29),
    "30-39": (30, 39),
    "40-49": (40, 49),
    "50-59": (50, 59),
    "60+":   (60, None),
}

# Washington Group Short Set domain columns on Disability. The
# `?disability=` filter takes either "any" (wg_disability_flag=True) or
# one of these domain names; domain filter checks for codes 03 / 04
# ("a lot of difficulty" / "cannot do at all") consistent with the
# wg_disability_flag computation in Disability.save().
_DISABILITY_DOMAINS = {"seeing", "hearing", "walking", "memory", "selfcare", "communication"}


def _household_filters(qs, params):
    """Apply the Registry household-list query params to `qs`. Used by
    both HouseholdViewSet.get_queryset and the aggregates action so the
    KPI strip reflects the same slice the list rows do."""
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(id__icontains=q)
            | Q(head_member__surname__icontains=q)
            | Q(head_member__first_name__icontains=q)
            | Q(parish__name__icontains=q),
        )
    sub_region = (params.get("sub_region") or "").strip()
    if sub_region:
        qs = qs.filter(sub_region_code=sub_region)
    band = (params.get("band") or "").strip()
    if band:
        qs = qs.filter(current_vulnerability_band=band)
    intake_source = (params.get("intake_source") or "").strip()
    if intake_source:
        qs = qs.filter(current_intake_source=intake_source)
    programme = (params.get("programme") or "").strip()
    if programme:
        qs = qs.filter(
            enrolments__programme__code=programme,
            enrolments__status="active",
        ).distinct()
    return qs


def _member_filters(qs, params):
    """Apply the Registry member-list query params to `qs`. Used by both
    MemberViewSet.get_queryset and the aggregates action."""
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(surname__icontains=q)
            | Q(first_name__icontains=q)
            | Q(id__icontains=q),
        )
    sex = (params.get("sex") or "").strip()
    if sex:
        qs = qs.filter(sex=sex)
    rel = (params.get("relationship_to_head") or "").strip()
    if rel:
        qs = qs.filter(relationship_to_head=rel)
    sub_region = (params.get("sub_region") or "").strip()
    if sub_region:
        qs = qs.filter(sub_region_code=sub_region)
    nin_status = (params.get("nin_status") or "").strip()
    if nin_status:
        qs = qs.filter(nin_status=nin_status)
    household_id = (params.get("household") or "").strip()
    if household_id:
        qs = qs.filter(household_id=household_id)
    age_band = (params.get("age_band") or "").strip()
    if age_band in _AGE_BANDS:
        lo, hi = _AGE_BANDS[age_band]
        if lo is not None:
            qs = qs.filter(age_years__gte=lo)
        if hi is not None:
            qs = qs.filter(age_years__lte=hi)
    disab = (params.get("disability") or "").strip()
    if disab == "any":
        qs = qs.filter(disability__wg_disability_flag=True)
    elif disab in _DISABILITY_DOMAINS:
        qs = qs.filter(**{f"disability__{disab}__in": ["03", "04"]})
    programme = (params.get("programme") or "").strip()
    if programme:
        qs = qs.filter(
            household__enrolments__programme__code=programme,
            household__enrolments__status="active",
        ).distinct()
    return qs


@extend_schema_view(
    list=extend_schema(tags=["data-management"], summary="List households"),
    retrieve=extend_schema(tags=["data-management"], summary="Retrieve a household"),
)
class HouseholdViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "household"
    queryset = Household.objects.all().order_by("-updated_at")
    serializer_class = HouseholdSerializer

    def get_queryset(self):
        return _household_filters(
            super().get_queryset(), self.request.query_params,
        )

    @extend_schema(
        tags=["data-management"],
        summary="Household aggregates for the Registry KPI strip",
        description=(
            "Returns total / registered / provisional_pending / "
            "programme_enrolled counts honouring the same filter params "
            "as the list endpoint (q, sub_region, band, intake_source, "
            "programme). Note: `provisional_pending` is always 0 against "
            "this surface because pre-promotion records live in "
            "apps.ingestion_hub.StageRecord, not Household. The two-"
            "system count lands when the DIH-pending tile feature ships."
        ),
    )
    @action(detail=False, methods=["get"], url_path="aggregates")
    def aggregates(self, request):
        qs = self.get_queryset()
        return Response({
            "total": qs.count(),
            "registered": qs.count(),
            "provisional_pending": 0,
            "programme_enrolled": qs.filter(
                enrolments__status="active",
            ).distinct().count(),
        })


@extend_schema_view(
    list=extend_schema(tags=["data-management"], summary="List members"),
    retrieve=extend_schema(tags=["data-management"], summary="Retrieve a member"),
)
class MemberViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "member"
    # US-005 — select_related the household location chain so the
    # Members list renders sub-region / district / parish / village
    # names without N+1 fetches.
    queryset = (
        Member.objects
        .select_related(
            "household__sub_region",
            "household__district",
            "household__parish",
            "household__village",
        )
        .order_by("household", "line_number")
    )
    serializer_class = MemberSerializer
    # US-S16-003 — tighter page-size cap on the highest-PII surface.
    # DefaultPagination caps at 500; MemberPagination caps at 100.
    pagination_class = MemberPagination

    def get_queryset(self):
        return _member_filters(
            super().get_queryset(), self.request.query_params,
        )

    @extend_schema(
        tags=["data-management"],
        summary="Member aggregates for the Registry KPI strip",
        description=(
            "Returns total_individuals / children_under_18 / "
            "elderly_60_plus / with_disability_wgss / female / "
            "nin_verified counts honouring the same filter params as the "
            "list endpoint. Sex code 2 = Female and nin_status code 1 = "
            "verified per the ChoiceList seed (US-S22-005c)."
        ),
    )
    @action(detail=False, methods=["get"], url_path="aggregates")
    def aggregates(self, request):
        qs = self.get_queryset()
        return Response({
            "total_individuals": qs.count(),
            "children_under_18": qs.filter(age_years__lt=18).count(),
            "elderly_60_plus": qs.filter(age_years__gte=60).count(),
            "with_disability_wgss": qs.filter(
                disability__wg_disability_flag=True,
            ).count(),
            "female": qs.filter(sex="2").count(),
            "nin_verified": qs.filter(nin_status="1").count(),
        })
