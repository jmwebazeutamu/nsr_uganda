from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from apps.security.abac import ScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin

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

    class Meta:
        model = Household
        fields = (
            "id", "head_member", "region", "sub_region", "district",
            "county", "sub_county", "parish", "village",
            "urban_rural", "enumeration_area", "household_number",
            "address_narrative",
            "gps_lat", "gps_lng", "gps_accuracy_m",
            "current_pmt_score", "current_vulnerability_band",
            "is_deleted", "created_at", "updated_at", "members",
        )


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
