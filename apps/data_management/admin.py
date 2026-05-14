from django.contrib import admin

from .models import Household, HouseholdVersion, Member, MemberVersion


class MemberInline(admin.TabularInline):
    model = Member
    fk_name = "household"
    extra = 0
    fields = ("line_number", "surname", "first_name", "sex", "age_years", "relationship_to_head", "nin_status")
    show_change_link = True
    raw_id_fields = ()


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
    inlines = [MemberInline]


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
