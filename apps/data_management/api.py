from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from apps.security.abac import ScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin
from apps.security.pagination import MemberPagination

from .models import Household, Member


class MemberSerializer(serializers.ModelSerializer):
    nin_value = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = (
            "id", "household", "line_number", "surname", "first_name", "other_name",
            "relationship_to_head", "sex", "date_of_birth", "age_years",
            "marital_status", "nationality", "residency_status",
            "birth_certificate_status", "nin_status", "nin_last4", "nin_value",
            "telephone_1", "telephone_2", "is_deleted", "merged_into",
        )

    def get_nin_value(self, obj) -> str | None:
        """NIN plaintext is never serialised. nin_last4 + nin_status are
        the operator-facing surface."""
        return None


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
    # US-S11-020 — surface the canonical_payload of the StageRecord
    # that promoted this household so the React detail screen can
    # render the questionnaire's housing / education / employment /
    # food-security / shocks blocks without inventing dedicated
    # detail tables. Returns null when no upstream StageRecord
    # exists (e.g., walk-in CAPI households whose payload wasn't
    # carried through the DIH pipeline).
    source_payload = serializers.SerializerMethodField()

    class Meta:
        model = Household
        fields = (
            "id", "head_member", "region", "sub_region", "district",
            "county", "sub_county", "parish", "village",
            "region_name", "sub_region_name", "district_name",
            "county_name", "sub_county_name", "parish_name", "village_name",
            "urban_rural", "enumeration_area", "household_number",
            "address_narrative",
            "gps_lat", "gps_lng", "gps_accuracy_m",
            "current_pmt_score", "current_vulnerability_band",
            "current_intake_source",
            "is_deleted", "created_at", "updated_at", "members",
            "source_payload",
        )

    def get_source_payload(self, obj) -> dict | None:
        """Joins back to the StageRecord that promoted this
        household. provisional_registry_id matches Household.id by
        construction (AC-DIH-PROMOTE-ATOMIC — same ULID is reused
        on promotion). Returns the canonical_payload JSON or None."""
        # Local import to avoid a circular at module-load time.
        from apps.ingestion_hub.models import StageRecord
        stage = StageRecord.objects.filter(
            provisional_registry_id=obj.id,
        ).only("canonical_payload").first()
        return stage.canonical_payload if stage else None


@extend_schema_view(
    list=extend_schema(tags=["data-management"], summary="List households"),
    retrieve=extend_schema(tags=["data-management"], summary="Retrieve a household"),
)
class HouseholdViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "household"
    queryset = Household.objects.all().order_by("-updated_at")
    serializer_class = HouseholdSerializer


@extend_schema_view(
    list=extend_schema(tags=["data-management"], summary="List members"),
    retrieve=extend_schema(tags=["data-management"], summary="Retrieve a member"),
)
class MemberViewSet(AuditReadMixin, ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    audit_entity_type = "member"
    queryset = Member.objects.all().order_by("household", "line_number")
    serializer_class = MemberSerializer
    # US-S16-003 — tighter page-size cap on the highest-PII surface.
    # DefaultPagination caps at 500; MemberPagination caps at 100.
    pagination_class = MemberPagination
