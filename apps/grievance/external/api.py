"""The partner-API configuration surface, for the console.

Everything this exposes was previously a shell command. That is the
problem it exists to fix: a `SourceSystem` appeared under Connector
runs with no screen saying where it came from, who recorded the
agreement, when the credential was entered, or whether the category
bindings that decide whether a case files are in place. The
configuration was real and invisible, which is the same as nobody
being responsible for it.

So `GET` answers "what is set up, by whom, and what is still
missing", and the actions are the three an operator actually takes:
test the connection, see what a pull WOULD do, and run it.

Writes are admin-only. A credential is the one thing here that lets
this registry read a complainant's identity out of another
organisation, and reading the configuration is not the same
permission as changing it.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.security.audit import emit as emit_audit

from . import CONNECTOR_NAME, SOURCE_CODE
from .client import StaacError
from .pull import configuration_blockers, credential_for, dry_run, pull
from .pull import test_connection as run_test_connection
from .service import file_held


def _source():
    from apps.ingestion_hub.models import SourceSystem

    return SourceSystem.objects.filter(code=SOURCE_CODE).first()


def _agreements() -> list[dict]:
    """The registry's own record of what it may receive.

    Including who approved it and when: "how did this get here" is
    the question this whole screen answers, and an agreement nobody
    is named against is the least answerable row on it.
    """
    from apps.ingestion_hub.models import DataProvisionAgreement

    today = date.today()
    rows = DataProvisionAgreement.objects.filter(
        source_system__code=SOURCE_CODE,
    ).order_by("-valid_from")
    in_force = set(
        rows.filter(valid_from__lte=today)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .values_list("id", flat=True),
    )
    return [
        {
            "reference": row.reference,
            "purpose": row.purpose,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
            "approved_by": row.approved_by,
            "signed_at": row.signed_at,
            "in_force": row.id in in_force,
        }
        for row in rows
    ]


def _bindings() -> dict:
    from apps.reference_data.models import ChoiceOption

    from ..intake import STAAC_CATEGORY_LIST

    options = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_CATEGORY_LIST,
    )
    total = options.count()
    bound = options.exclude(canonical_code__isnull=True).count()
    return {
        "list_name": STAAC_CATEGORY_LIST,
        "total": total,
        "bound": bound,
        "unbound": [
            {"code": o.code, "label": o.label}
            for o in options.filter(canonical_code__isnull=True)
            .order_by("sort_order")
        ],
    }


def _held() -> list[dict]:
    """What is waiting on configuration, grouped by what would fix it."""
    from django.db.models import Count

    from ..models import HandoverOutcome, StaacHandover

    return list(
        StaacHandover.objects.filter(outcome=HandoverOutcome.HELD)
        .values("held_reason", "held_source_code")
        .annotate(count=Count("id"))
        .order_by("-count"),
    )


def _runs(limit: int = 10) -> list[dict]:
    """Recent runs for this source — the rows that prompted the
    question "how did STAAC_GRM get under Connector runs"."""
    from apps.ingestion_hub.models import ConnectorRun

    return [
        {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "received": run.records_received,
            "promoted": run.records_promoted,
            "quarantined": run.records_quarantined,
            "rejected": run.records_rejected,
            "note": run.note,
        }
        for run in ConnectorRun.objects
        .filter(connector__source_system__code=SOURCE_CODE)
        .order_by("-started_at")[:limit]
    ]


class _CredentialIn(serializers.Serializer):
    environment = serializers.CharField(max_length=32)
    base_url = serializers.URLField(max_length=255)
    #: Write-only and never echoed. STAAC shows its token once and
    #: keeps only a digest; this holds the same line.
    token = serializers.CharField(
        max_length=512, required=False, allow_blank=True, write_only=True,
    )
    is_active = serializers.BooleanField(required=False, default=True)


class PartnerApiConfigView(APIView):
    """What is configured, and what is still missing."""

    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["grm"],
        summary="STAAC partner API configuration and readiness",
        responses={200: OpenApiResponse(description="Configuration state")},
    )
    def get(self, request):
        from ..models import StaacCredential

        source = _source()
        connector = None
        if source is not None:
            connector = source.connectors.filter(
                name=CONNECTOR_NAME,
            ).first()

        credentials = [
            {
                "id": c.id,
                "environment": c.environment,
                "base_url": c.base_url,
                "is_active": c.is_active,
                "has_token": bool(c.token_encrypted),
                "resuming": bool(c.cursor),
                "last_pulled_at": c.last_pulled_at,
                "created_at": c.created_at,
            }
            for c in StaacCredential.objects.order_by("environment")
        ]

        return Response({
            "source": None if source is None else {
                "code": source.code,
                "name": source.name,
                "kind": source.kind,
                "description": source.description,
                "is_active": source.is_active,
                # The answer to "how did this get here".
                "registered_by": "migration grievance.0017",
                "created_at": source.created_at,
            },
            "connector": None if connector is None else {
                "name": connector.name, "is_active": connector.is_active,
            },
            "credentials": credentials,
            "agreements": _agreements(),
            "category_bindings": _bindings(),
            "held": _held(),
            "runs": _runs(),
            "blockers": configuration_blockers(),
            "push": {
                "path": "/api/v1/grm/partners/staac/handovers/",
                "configured": bool(_push_secret()),
                "note": (
                    "Refuses every request until a shared secret is set. "
                    "The partner contract leaves the receiver's "
                    "authentication profile to be agreed between the IG "
                    "and NSR, so this is not switched on from here."
                ),
            },
        })

    @extend_schema(
        tags=["grm"], summary="Store a partner credential",
        request=_CredentialIn,
        responses={200: OpenApiResponse(description="Stored")},
    )
    def post(self, request):
        from ..models import StaacCredential

        if not IsAdminUser().has_permission(request, self):
            return Response(
                {"detail": "Only an administrator may change this."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = _CredentialIn(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        row = StaacCredential.objects.filter(
            environment=data["environment"],
        ).first()
        token = (data.get("token") or "").strip()
        if row is None and not token:
            return Response(
                {"detail": "A token is required when adding a credential."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if row is None:
            row = StaacCredential(environment=data["environment"])
        row.base_url = data["base_url"]
        row.is_active = data.get("is_active", True)
        if row.is_active:
            # Exactly one environment is live. `credential_for`
            # refuses to choose between two active credentials — on
            # purpose, since "production" sorts before "sandbox" — so
            # without this, pointing at production from the console
            # would be impossible rather than merely awkward:
            # activating the new one would leave two and refuse both.
            StaacCredential.objects.filter(is_active=True).exclude(
                environment=row.environment,
            ).update(is_active=False)
        if token:
            # Plaintext in: the column encrypts on write. And a new
            # token invalidates the cursor, which STAAC signs per
            # credential — resuming with the old one would be a silent
            # resume from nowhere.
            row.token_encrypted = token.encode("utf-8")
            row.cursor = ""
        row.save()

        emit_audit(
            "update", "staac.credential", row.id,
            actor=request.user.username or "admin",
            reason="partner credential stored from the console",
            # The token is never in the event, only the fact of it.
            field_changes={
                "environment": row.environment, "base_url": row.base_url,
                "is_active": row.is_active, "token_replaced": bool(token),
                # Which environment this registry now talks to is the
                # single most consequential thing on this screen.
                "now_live": row.environment if row.is_active else "",
            },
        )
        return Response({"environment": row.environment, "stored": True})


def _push_secret() -> str:
    from django.conf import settings

    return str(getattr(settings, "GRM_STAAC_PUSH_SECRET", "") or "")


class PartnerApiTestView(APIView):
    """Reach STAAC and come back. Files nothing."""

    permission_classes = (IsAdminUser,)

    @extend_schema(
        tags=["grm"], summary="Test the partner connection",
        responses={200: OpenApiResponse(description="Connection result")},
    )
    def post(self, request):
        result = run_test_connection(
            environment=str(request.data.get("environment") or ""),
        )
        emit_audit(
            "test_connection", "staac.credential",
            str(request.data.get("environment") or "default"),
            actor=request.user.username or "admin",
            reason="partner connection test",
            field_changes={"ok": result.ok, "latency_ms": result.latency_ms},
        )
        return Response({
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "detail": result.server_version or result.error or "",
        })


class PartnerApiDryRunView(APIView):
    """What a pull would do, having done none of it."""

    permission_classes = (IsAdminUser,)

    @extend_schema(
        tags=["grm"], summary="Dry-run the partner pull",
        responses={200: OpenApiResponse(description="What would happen")},
    )
    def post(self, request):
        try:
            report = dry_run(
                environment=str(request.data.get("environment") or ""),
            )
        except StaacError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        emit_audit(
            "read", "staac.pull", "dry-run",
            actor=request.user.username or "admin", actor_kind="user",
            reason=f"dry run: {report.summary()}",
            field_changes={
                "listed": report.listed, "examined": report.examined,
                "would_file": report.would_file,
                "would_hold": report.would_hold,
            },
        )
        return Response({
            "summary": report.summary(),
            "listed": report.listed,
            "examined": report.examined,
            "would_file": report.would_file,
            "would_hold": report.would_hold,
            "already_held": report.already_held,
            "blockers": report.blockers,
            "errors": report.errors,
            "rows": [
                {
                    # Generic keys: the screen that renders this row
                    # must not learn whose category this is, or a
                    # second integration needs a second renderer.
                    "tracking_number": r.tracking_number,
                    "source_label": r.staac_category,
                    "source_detail": r.parish_key,
                    "verdict": r.verdict,
                    "nsr_category": r.nsr_category,
                    "held_reason": r.held_reason,
                    "held_source_code": r.held_source_code,
                    "detail": r.detail,
                    "warnings": list(r.warnings),
                }
                for r in report.rows
            ],
        })


class PartnerApiRunView(APIView):
    """Run the pull for real, or file what is already held."""

    permission_classes = (IsAdminUser,)

    @extend_schema(
        tags=["grm"], summary="Run the partner pull",
        responses={200: OpenApiResponse(description="Run result")},
    )
    def post(self, request):
        actor = request.user.username or "admin"
        if request.data.get("file_held"):
            results = file_held(actor=actor)
            filed = sum(1 for r in results if r.created)
            return Response({
                "summary": (
                    f"{len(results)} held snapshot(s) re-applied, "
                    f"{filed} filed"
                ),
                "filed": filed, "still_held": len(results) - filed,
            })
        try:
            report = pull(
                environment=str(request.data.get("environment") or ""),
                restart=bool(request.data.get("restart")),
                actor=actor,
            )
        except StaacError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "summary": report.summary(),
            "run_id": report.run_id,
            "listed": report.listed, "fetched": report.fetched,
            "filed": report.filed, "held": report.held,
            "already_held": report.already_held,
            "warnings": report.warnings, "errors": report.errors,
            "correlation_id": report.correlation_id,
        })
