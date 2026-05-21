from django.contrib import admin

from .models import (
    AssetOwnership,
    AssetOwnershipVersion,
    CopingStrategy,
    CopingStrategyVersion,
    Crop,
    CropVersion,
    Disability,
    DisabilityVersion,
    # US-S22-DE-01 detail entities — per-Household
    Dwelling,
    # US-S22-DE-01 version mirrors
    DwellingVersion,
    Education,
    EducationVersion,
    Employment,
    EmploymentVersion,
    FoodConsumption,
    FoodConsumptionVersion,
    FoodSecurity,
    FoodSecurityVersion,
    # US-S22-DE-01 detail entities — per-Member
    Health,
    HealthVersion,
    # Core (pre-existing)
    Household,
    HouseholdVersion,
    Livelihood,
    LivelihoodVersion,
    Livestock,
    LivestockVersion,
    Member,
    MemberVersion,
    Shock,
    ShockVersion,
    Utilities,
    UtilitiesVersion,
)


class MemberInline(admin.TabularInline):
    model = Member
    fk_name = "household"
    extra = 0
    fields = ("line_number", "surname", "first_name", "sex", "age_years", "relationship_to_head", "nin_status")
    show_change_link = True
    raw_id_fields = ()


# --- US-S22-DE-01 inlines: per-Household one-to-one ----------------------


class DwellingInline(admin.StackedInline):
    model = Dwelling
    extra = 0
    can_delete = False
    show_change_link = True


class UtilitiesInline(admin.StackedInline):
    model = Utilities
    extra = 0
    can_delete = False
    show_change_link = True


class LivelihoodInline(admin.StackedInline):
    model = Livelihood
    extra = 0
    can_delete = False
    show_change_link = True


class FoodSecurityInline(admin.StackedInline):
    model = FoodSecurity
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = ("fies_raw_score",)


class FoodConsumptionInline(admin.StackedInline):
    model = FoodConsumption
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = ("fcs_score",)


# --- US-S22-DE-01 inlines: per-Household repeat groups ------------------


class AssetOwnershipInline(admin.TabularInline):
    model = AssetOwnership
    extra = 0
    fields = ("asset_type", "count", "is_deleted")
    show_change_link = True


class CropInline(admin.TabularInline):
    model = Crop
    extra = 0
    fields = ("crop_name", "rank_order", "is_deleted")
    show_change_link = True


class LivestockInline(admin.TabularInline):
    model = Livestock
    extra = 0
    fields = ("livestock_type", "count", "is_deleted")
    show_change_link = True


class ShockInline(admin.TabularInline):
    model = Shock
    extra = 0
    fields = ("shock_type", "severity", "event_date", "is_deleted")
    show_change_link = True


class CopingStrategyInline(admin.TabularInline):
    model = CopingStrategy
    extra = 0
    fields = ("strategy_type", "category", "frequency", "used_flag", "is_deleted")
    show_change_link = True


# --- US-S22-DE-01 inlines: per-Member one-to-one ------------------------


class HealthInline(admin.StackedInline):
    model = Health
    extra = 0
    can_delete = False
    show_change_link = True
    # chronic_illness_types_encrypted is bytes — admin display is unsafe;
    # use the model's get_chronic_illness_types() helper via a custom
    # serializer when the DPO admin view lands. For now, hide.
    exclude = ("chronic_illness_types_encrypted",)


class DisabilityInline(admin.StackedInline):
    model = Disability
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = ("wg_disability_flag",)


class EducationInline(admin.StackedInline):
    model = Education
    extra = 0
    can_delete = False
    show_change_link = True


class EmploymentInline(admin.StackedInline):
    model = Employment
    extra = 0
    can_delete = False
    show_change_link = True


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("id", "head_member", "village", "parish", "urban_rural", "is_deleted", "updated_at")
    list_filter = ("urban_rural", "is_deleted")
    search_fields = ("id", "address_narrative", "household_number")
    raw_id_fields = (
        "head_member", "region", "sub_region", "district",
        "county", "sub_county", "parish", "village",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-updated_at",)
    inlines = [
        MemberInline,
        DwellingInline, UtilitiesInline, LivelihoodInline,
        FoodSecurityInline, FoodConsumptionInline,
        AssetOwnershipInline, CropInline, LivestockInline,
        ShockInline, CopingStrategyInline,
    ]


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("id", "surname", "first_name", "sex", "age_years", "household", "nin_status", "nin_last4")
    list_filter = ("sex", "nin_status", "is_deleted")
    search_fields = ("id", "surname", "first_name", "other_name", "telephone_1", "telephone_2")
    raw_id_fields = ("household", "merged_into")
    readonly_fields = ("id", "created_at", "updated_at", "nin_value", "nin_hash")
    ordering = ("household", "line_number")

    fieldsets = (
        (None, {"fields": ("id", "household", "line_number")}),
        ("Identity", {"fields": (
            "surname", "first_name", "other_name", "relationship_to_head",
            "sex", "date_of_birth", "age_years",
        )}),
        ("Status", {"fields": (
            "marital_status", "nationality", "residency_status", "birth_certificate_status",
        )}),
        ("NIN", {
            "fields": ("nin_status", "nin_last4", "nin_value", "nin_hash"),
            "description": (
                "nin_value is encrypted; nin_hash is the join key. "
                "Plaintext NIN never appears in admin."
            ),
        }),
        ("Contact", {"fields": (
            "telephone_1", "telephone_2", "telephone_in_name_flag", "mobile_money_flag",
        )}),
        ("Family", {"fields": (
            "mother_alive_flag", "father_alive_flag",
            "mother_line_number", "father_line_number",
        )}),
        ("Documents", {"fields": ("identification_documents",)}),
        ("State", {"fields": (
            "is_deleted", "deleted_at", "merged_into", "created_at", "updated_at",
        )}),
    )

    inlines = [
        HealthInline, DisabilityInline,
        EducationInline, EmploymentInline,
    ]


@admin.register(HouseholdVersion)
class HouseholdVersionAdmin(admin.ModelAdmin):
    list_display = ("household", "version_number", "effective_from", "effective_to", "created_at")
    search_fields = ("household__id", "change_request_id")
    raw_id_fields = ("household",)
    readonly_fields = ("created_at",)
    ordering = ("household", "-version_number")


@admin.register(MemberVersion)
class MemberVersionAdmin(admin.ModelAdmin):
    list_display = ("member", "version_number", "effective_from", "effective_to", "created_at")
    search_fields = ("member__id", "change_request_id")
    raw_id_fields = ("member",)
    readonly_fields = ("created_at",)
    ordering = ("member", "-version_number")


# ===========================================================================
# Detail-entity ModelAdmins (US-S22-DE-03)
# ===========================================================================


class _DetailAdminBase(admin.ModelAdmin):
    readonly_fields = ("id", "sub_region_code", "created_at", "updated_at")
    list_filter = ("is_deleted",)
    ordering = ("-updated_at",)


@admin.register(Dwelling)
class DwellingAdmin(_DetailAdminBase):
    list_display = ("id", "household", "tenure", "dwelling_type", "roof_material", "updated_at")
    search_fields = ("id", "household__id")
    raw_id_fields = ("household",)


@admin.register(Utilities)
class UtilitiesAdmin(_DetailAdminBase):
    list_display = ("id", "household", "cooking_fuel", "drinking_water_source", "toilet_facility", "updated_at")
    search_fields = ("id", "household__id")
    raw_id_fields = ("household",)


@admin.register(Livelihood)
class LivelihoodAdmin(_DetailAdminBase):
    list_display = ("id", "household", "main_livelihood", "land_hectares", "land_ownership", "updated_at")
    search_fields = ("id", "household__id")
    raw_id_fields = ("household",)


@admin.register(FoodSecurity)
class FoodSecurityAdmin(_DetailAdminBase):
    list_display = ("id", "household", "fies_raw_score", "updated_at")
    search_fields = ("id", "household__id")
    raw_id_fields = ("household",)
    readonly_fields = _DetailAdminBase.readonly_fields + ("fies_raw_score",)


@admin.register(FoodConsumption)
class FoodConsumptionAdmin(_DetailAdminBase):
    list_display = ("id", "household", "fcs_score", "updated_at")
    search_fields = ("id", "household__id")
    raw_id_fields = ("household",)
    readonly_fields = _DetailAdminBase.readonly_fields + ("fcs_score",)


@admin.register(AssetOwnership)
class AssetOwnershipAdmin(_DetailAdminBase):
    list_display = ("id", "household", "asset_type", "count", "updated_at")
    list_filter = ("is_deleted", "asset_type")
    search_fields = ("id", "household__id", "asset_type")
    raw_id_fields = ("household",)


@admin.register(Crop)
class CropAdmin(_DetailAdminBase):
    list_display = ("id", "household", "crop_name", "rank_order", "updated_at")
    list_filter = ("is_deleted", "crop_name")
    search_fields = ("id", "household__id", "crop_name")
    raw_id_fields = ("household",)


@admin.register(Livestock)
class LivestockAdmin(_DetailAdminBase):
    list_display = ("id", "household", "livestock_type", "count", "updated_at")
    list_filter = ("is_deleted", "livestock_type")
    search_fields = ("id", "household__id", "livestock_type")
    raw_id_fields = ("household",)


@admin.register(Shock)
class ShockAdmin(_DetailAdminBase):
    list_display = ("id", "household", "shock_type", "severity", "event_date", "updated_at")
    list_filter = ("is_deleted", "shock_type", "severity")
    search_fields = ("id", "household__id", "shock_type")
    raw_id_fields = ("household",)


@admin.register(CopingStrategy)
class CopingStrategyAdmin(_DetailAdminBase):
    list_display = ("id", "household", "strategy_type", "category", "frequency", "used_flag", "updated_at")
    list_filter = ("is_deleted", "category", "strategy_type")
    search_fields = ("id", "household__id", "strategy_type")
    raw_id_fields = ("household",)


@admin.register(Health)
class HealthAdmin(_DetailAdminBase):
    list_display = ("id", "member", "chronic_illness_flag", "updated_at")
    search_fields = ("id", "member__id")
    raw_id_fields = ("member",)
    # chronic_illness_types_encrypted is bytes; readonly to avoid accidental
    # writes. Use Health.set_chronic_illness_types() in code.
    readonly_fields = _DetailAdminBase.readonly_fields + ("chronic_illness_types_encrypted",)


@admin.register(Disability)
class DisabilityAdmin(_DetailAdminBase):
    list_display = ("id", "member", "wg_disability_flag", "updated_at")
    list_filter = ("is_deleted", "wg_disability_flag")
    search_fields = ("id", "member__id")
    raw_id_fields = ("member",)
    readonly_fields = _DetailAdminBase.readonly_fields + ("wg_disability_flag",)


@admin.register(Education)
class EducationAdmin(_DetailAdminBase):
    list_display = ("id", "member", "literacy_status", "highest_grade", "currently_attending", "updated_at")
    search_fields = ("id", "member__id")
    raw_id_fields = ("member",)


@admin.register(Employment)
class EmploymentAdmin(_DetailAdminBase):
    list_display = ("id", "member", "main_activity_last_30d", "sector", "employment_status", "updated_at")
    list_filter = ("is_deleted", "sector")
    search_fields = ("id", "member__id")
    raw_id_fields = ("member",)


# --- Version admins -----------------------------------------------------


class _VersionAdminBase(admin.ModelAdmin):
    list_display = ("__str__", "version_number", "effective_from", "effective_to", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("-version_number",)


_VERSION_MODELS = (
    DwellingVersion, UtilitiesVersion, LivelihoodVersion,
    FoodSecurityVersion, FoodConsumptionVersion,
    AssetOwnershipVersion, CropVersion, LivestockVersion,
    ShockVersion, CopingStrategyVersion,
    HealthVersion, DisabilityVersion, EducationVersion, EmploymentVersion,
)

for _model in _VERSION_MODELS:
    admin.site.register(_model, _VersionAdminBase)
