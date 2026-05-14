from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from .models import GeographicUnit


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
