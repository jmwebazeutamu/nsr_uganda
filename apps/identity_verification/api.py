"""HTTP surface for the NIRA sandbox mock.

Exposes POST /api/v1/idv/nira-mock/verify so other modules (and external
test harnesses) can call it exactly as they would call the real NIRA
service. Production deploys point the IDV client at the real base URL;
this endpoint is gated by DEBUG so it cannot ship to production.
"""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .mock import NiraError, verify_nin


class NiraVerifyRequestSerializer(serializers.Serializer):
    nin = serializers.CharField(max_length=14, min_length=14)


class NiraMockVerifyView(APIView):
    """Sandbox-only; refuses to serve when DEBUG is False."""

    @extend_schema(
        tags=["idv"],
        summary="NIRA sandbox mock — verify a NIN",
        description=(
            "Deterministic stand-in for the NIRA NIN verify endpoint. The "
            "outcome is keyed off the NIN suffix so callers can exercise "
            "match / no_match / mismatch / service_unavailable paths "
            "without fixtures. Sandbox-only — refuses to serve outside DEBUG."
        ),
        request=NiraVerifyRequestSerializer,
        responses={
            200: OpenApiResponse(description="Verification result"),
            400: OpenApiResponse(description="Malformed NIN"),
            404: OpenApiResponse(description="Mock unavailable (DEBUG=False)"),
            503: OpenApiResponse(description="Simulated NIRA outage"),
        },
    )
    def post(self, request):
        if not settings.DEBUG:
            raise NotFound("NIRA mock is disabled outside DEBUG")
        ser = NiraVerifyRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = verify_nin(ser.validated_data["nin"])
        except NiraError as e:
            return Response({"status": "service_unavailable", "detail": str(e)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if result.get("status") == "bad_format":
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)
