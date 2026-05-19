from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from apps.security.abac import ScopedQuerysetMixin
from apps.security.audit_views import AuditReadMixin
from apps.security.pagination import MemberPagination

from .choice_field_map import (
    HOUSEHOLD_FIELDS,
    MEMBER_FIELDS,
    apply_payload_labels,
)
from .models import Household, Member


def _intake_date(household):
    """as_of date for label resolution on a Household. Falls back to
    created_at (or today via the resolver) when no upstream
    StageRecord is available."""
    from apps.ingestion_hub.models import StageRecord
    stage = (
        StageRecord.objects.filter(provisional_registry_id=household.id)
        .only("created_at")
        .first()
    )
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


class MemberSerializer(serializers.ModelSerializer):
    nin_value = serializers.SerializerMethodField()

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
        )

    def get_nin_value(self, obj) -> str | None:
        """NIN plaintext is never serialised. nin_last4 + nin_status are
        the operator-facing surface."""
        return None


_attach_label_methodfields(MemberSerializer, MEMBER_FIELDS)


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
        )

    def get_source_payload(self, obj) -> dict | None:
        """Joins back to the StageRecord that promoted this
        household. provisional_registry_id matches Household.id by
        construction (AC-DIH-PROMOTE-ATOMIC — same ULID is reused
        on promotion). Returns the canonical_payload JSON or None."""
        from apps.ingestion_hub.models import StageRecord
        stage = StageRecord.objects.filter(
            provisional_registry_id=obj.id,
        ).only("canonical_payload").first()
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
