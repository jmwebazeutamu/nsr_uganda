"""The push half: STAAC posts a snapshot, this stores it.

Pull is the required reconciliation path and push is an optimisation
on top of it — spec §6: "Pull remains the required, authenticated
reconciliation path even when push is enabled." So this deliberately
shares everything that matters with the pull: the same `file_snapshot`,
the same landing table, the same agreement gate, the same
`(handover_id, exchange_version)` key. A pushed record and a pulled
one are the same record, and the one that arrives second is a
duplicate that must succeed without creating anything.

What this endpoint is NOT
-------------------------
It is not part of the console API and carries no session. STAAC is a
machine, authenticated as one. Until the IG and NSR agree the
receiver's authentication profile — spec §6.1 is explicit that mTLS,
client certificates and the STAAC-to-NSR outbound credential scheme
are NOT implemented in their v1 — this refuses every request unless a
shared secret is configured, because an unauthenticated endpoint that
writes grievances is worse than no endpoint.

`Idempotency-Key` is `partner:<handover_id>:<exchange_version>:handover`.
The spec requires NSR to enforce uniqueness on it as well as on the
pair, and the two must agree: a key naming a different handover than
the body is a bug in one of the two systems and is refused rather than
resolved in favour of either.
"""

from __future__ import annotations

import hmac

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.security.audit import emit as emit_audit

from . import PULL_ACTOR
from .client import StaacError

#: Who the audit chain records for a pushed record, distinct from a
#: pulled one so the two are tellable apart in the chain.
PUSH_ACTOR = "staac-push"

#: Spec §6: `partner:<handover_id>:<exchange_version>:handover`.
IDEMPOTENCY_PREFIX = "partner:"
IDEMPOTENCY_KIND = "handover"


class _Pushed(serializers.Serializer):
    """Only the shape the registry depends on is validated.

    The snapshot is stored verbatim and interpreted by the same code
    that interprets a pulled one, so validating its interior here
    would be a second, divergent reading of one payload.
    """

    handover_id = serializers.CharField(max_length=64)
    exchange_version = serializers.IntegerField(min_value=1)


def _expected_secret() -> str:
    return str(getattr(settings, "GRM_STAAC_PUSH_SECRET", "") or "")


def _authentic(request) -> bool:
    """Constant-time comparison of the agreed shared secret.

    A placeholder for the profile §6.1 says is still to be agreed —
    named as one in the settings comment — not a scheme this registry
    invented and now depends on.
    """
    expected = _expected_secret()
    if not expected:
        return False
    sent = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not sent.startswith(prefix):
        return False
    return hmac.compare_digest(sent[len(prefix):], expected)


def parse_idempotency_key(raw: str) -> tuple[str, int]:
    """`partner:<handover_id>:<version>:handover` -> (id, version).

    Raises ValueError on anything else. The key is a claim about
    which record this is, and a claim that cannot be read is not one
    to guess at.
    """
    parts = str(raw or "").split(":")
    if len(parts) != 4 or f"{parts[0]}:" != IDEMPOTENCY_PREFIX:
        raise ValueError(
            "Idempotency-Key must be "
            "partner:<handover_id>:<exchange_version>:handover",
        )
    if parts[3] != IDEMPOTENCY_KIND:
        raise ValueError(f"unsupported idempotency kind {parts[3]!r}")
    try:
        version = int(parts[2])
    except ValueError as exc:
        raise ValueError(f"{parts[2]!r} is not an exchange version") from exc
    if version < 1:
        raise ValueError(f"{parts[2]!r} is not an exchange version")
    return parts[1], version


class StaacPushReceiver(APIView):
    """Receive one approved handover snapshot from STAAC."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    http_method_names = ["post", "options"]

    @extend_schema(
        tags=["grm"],
        summary="Receive a grievance handover pushed by STAAC",
        request=_Pushed,
        responses={
            202: OpenApiResponse(description="Stored. Filed or held."),
            400: OpenApiResponse(description="Malformed key or body."),
            401: OpenApiResponse(description="Not authenticated as STAAC."),
            409: OpenApiResponse(description="Key and body disagree."),
            503: OpenApiResponse(
                description="No agreement on record, or push not configured.",
            ),
        },
    )
    def post(self, request):
        if not _authentic(request):
            # Same answer for "no secret configured" and "wrong
            # secret": a caller must not learn which.
            return Response(
                {"detail": "Not authenticated."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            key_id, key_version = parse_idempotency_key(
                request.headers.get("Idempotency-Key", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)

        body = request.data if isinstance(request.data, dict) else {}
        ser = _Pushed(data=body)
        if not ser.is_valid():
            return Response({"detail": ser.errors},
                            status=status.HTTP_400_BAD_REQUEST)

        if (
            str(ser.validated_data["handover_id"]) != key_id
            or int(ser.validated_data["exchange_version"]) != key_version
        ):
            # One of the two systems has a bug. Choosing a winner
            # would file a complaint under the wrong identity.
            return Response(
                {"detail": "Idempotency-Key does not describe this snapshot."},
                status=status.HTTP_409_CONFLICT,
            )

        from apps.ingestion_hub.services import DihError, start_connector_run

        from .pull import connector_for_staac
        from .service import file_snapshot

        try:
            run = start_connector_run(connector_for_staac(), actor=PUSH_ACTOR)
        except (DihError, StaacError) as exc:
            # 503, not 400: nothing is wrong with STAAC's request. The
            # receiving side is not configured to accept it, and the
            # spec tells STAAC to retry a non-2xx — which is right,
            # because once the agreement is recorded the retry works.
            return Response(
                {"detail": f"Not ready to receive: {exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        result = file_snapshot(
            body, run=run, handover_id=key_id, exchange_version=key_version,
            correlation_id=str(request.headers.get("X-Correlation-ID") or ""),
            actor=PUSH_ACTOR,
        )
        self._close(run, result)

        emit_audit(
            "create", "staac.push", result.handover.id, actor=PUSH_ACTOR,
            actor_kind="system",
            reason=f"pushed handover {key_id} v{key_version}",
            field_changes={
                "handover_id": key_id,
                "exchange_version": key_version,
                "outcome": result.handover.outcome,
                "duplicate": not result.created,
            },
        )

        # 202, not 201: the snapshot is durably accepted, which is
        # what the spec asks a 2xx to mean, but accepted is not the
        # same as filed — it may be held, and saying "created" would
        # tell STAAC a grievance exists when one may not.
        return Response(
            {
                "handover_id": key_id,
                "exchange_version": key_version,
                "outcome": result.handover.outcome,
                "duplicate": not result.created,
                "warnings": list(result.warnings),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _close(run, result) -> None:
        from django.db.models import F
        from django.utils import timezone

        from apps.grievance.models import HandoverOutcome
        from apps.ingestion_hub.models import ConnectorRun, ConnectorRunStatus

        filed = int(result.handover.outcome == HandoverOutcome.FILED)
        ConnectorRun.objects.filter(pk=run.pk).update(
            status=ConnectorRunStatus.SUCCEEDED,
            finished_at=timezone.now(),
            note=f"push {result.handover.handover_id} -> {result.handover.outcome}",
            records_promoted=F("records_promoted") + filed,
            records_quarantined=F("records_quarantined") + (1 - filed),
        )
