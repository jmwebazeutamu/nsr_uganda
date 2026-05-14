from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.data_management.models import Household

from .models import PMTModelVersion, PMTResult
from .services import recompute_for_household


class PMTModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTModelVersion
        fields = ("id", "version", "description", "status", "author", "approved_by",
                  "approved_at", "effective_from", "variables", "intercept",
                  "validation_r_squared", "band_cutoffs")


class PMTResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTResult
        fields = ("id", "household", "model_version", "score", "band",
                  "inputs_snapshot", "triggered_by", "computed_at")


@extend_schema_view(
    list=extend_schema(tags=["pmt"], summary="List PMT model versions"),
    retrieve=extend_schema(tags=["pmt"], summary="Retrieve a PMT model version"),
)
class PMTModelVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PMTModelVersion.objects.all().order_by("-version")
    serializer_class = PMTModelVersionSerializer
    filterset_fields = ["status"]


@extend_schema_view(
    list=extend_schema(tags=["pmt"], summary="List PMT results"),
    retrieve=extend_schema(tags=["pmt"], summary="Retrieve a PMT result"),
)
class PMTResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PMTResult.objects.all().order_by("-computed_at")
    serializer_class = PMTResultSerializer
    filterset_fields = ["band", "triggered_by"]

    @extend_schema(
        tags=["pmt"],
        summary="Trigger a PMT recompute for a household",
        request=None,
        responses={200: PMTResultSerializer, 400: OpenApiResponse(description="no ACTIVE model")},
    )
    @action(detail=False, methods=["post"], url_path="recompute/(?P<household_id>[^/.]+)")
    def recompute(self, request, household_id=None):
        try:
            hh = Household.objects.get(pk=household_id)
        except Household.DoesNotExist:
            return Response({"detail": "household not found"},
                            status=status.HTTP_404_NOT_FOUND)
        result = recompute_for_household(
            hh, triggered_by="manual", actor=request.user.username or "system",
        )
        if result is None:
            return Response({"detail": "no ACTIVE PMT model version"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)
