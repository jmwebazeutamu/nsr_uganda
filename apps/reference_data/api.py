from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from .models import ChoiceList, ChoiceOption, GeographicUnit


class GeographicUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeographicUnit
        fields = ("id", "level", "code", "name", "parent", "effective_from", "effective_to", "status")


@extend_schema_view(
    list=extend_schema(tags=["reference-data"], summary="List geographic units"),
    retrieve=extend_schema(tags=["reference-data"], summary="Retrieve a geographic unit"),
)
class GeographicUnitViewSet(viewsets.ReadOnlyModelViewSet):
    """UBOS administrative hierarchy. Read-only; sourced from the UBOS loader."""

    queryset = GeographicUnit.objects.all().order_by("level", "code")
    serializer_class = GeographicUnitSerializer
    filterset_fields = ["level", "status", "parent"]


# --- US-116 ChoiceList read API ---------------------------------------------

class ChoiceOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChoiceOption
        fields = ("id", "code", "label", "language", "parent_code",
                  "sort_order", "status")


class ChoiceListSerializer(serializers.ModelSerializer):
    """Embeds the option set so a single round-trip from the
    questionnaire renderer (US-117) can pull the whole list. The
    write surface (create / update under approval) ships in US-116b
    along with the service-layer transitions."""

    options = ChoiceOptionSerializer(many=True, read_only=True)

    class Meta:
        model = ChoiceList
        fields = (
            "id", "list_name", "version", "description",
            "effective_from", "effective_to", "status",
            "author", "approved_by", "approved_at",
            "submitted_at", "approval_note", "rejection_reason",
            "options",
        )


@extend_schema_view(
    list=extend_schema(tags=["reference-data"], summary="List choice lists"),
    retrieve=extend_schema(tags=["reference-data"], summary="Retrieve a choice list"),
)
class ChoiceListViewSet(viewsets.ReadOnlyModelViewSet):
    """Versioned questionnaire code-lists. Read-only in US-116; write
    surface + approval workflow lands in US-116b."""

    queryset = (
        ChoiceList.objects
        .prefetch_related("options")
        .order_by("list_name", "-version")
    )
    serializer_class = ChoiceListSerializer
    filterset_fields = ["status", "list_name"]
