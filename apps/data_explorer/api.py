"""DATA-EXP DRF surface — every endpoint is read-only except /aggregate
and /handoff (which are POST-only side-effects with audit on every
response code, including 422/429/503).

Per ADR-0023 D9: when DATA_EXPLORER_ENABLED is False, every endpoint
returns 503 (the permission class raises FeatureFlagOff before
dispatch).
"""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.security.audit import emit as emit_audit
from apps.security.audit_views import _client_ip

from .catalogue import MetadataCatalog
from .handoff import perform_handoff
from .permissions import FlagEnabledPublic, IsExplorerRoleAndFlagEnabled
from .query_builder import (
    AggregateQueryService,
    StaleMatviewError,
    write_query_log,
)
from .throttle import PrivacyClassThrottle, Throttled
from .validators import ValidationError, validate

# ---------------------------------------------------------------------------
# Serialisation helpers — kept inline so the schema is one file. The
# OpenAPI doc is authoritative; this layer is just a JSON projection.

def _serialise_dataset(ds) -> dict:
    return {
        "id": str(ds.id),
        "code": ds.code,
        "label": ds.label,
        "description": ds.description,
        "source_matview": ds.source_matview,
        "geographic_floor": ds.geographic_floor,
        "has_coverage_baseline": ds.has_coverage_baseline,
        "has_synthetic_sample": ds.has_synthetic_sample,
        "privacy_class": {
            "code": ds.privacy_class.code,
            "label": ds.privacy_class.label,
            "k_floor": ds.privacy_class.k_floor,
        },
        "refresh_cadence": {
            "code": ds.refresh_cadence.code,
            "label": ds.refresh_cadence.label,
            "interval_seconds": ds.refresh_cadence.interval_seconds,
        },
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }


def _serialise_variable(v) -> dict:
    return {
        "id": str(v.id),
        "code": v.code,
        "label": v.label,
        "description": v.description,
        "dataset": {
            "id": str(v.dataset_id),
            "code": v.dataset.code,
            "label": v.dataset.label,
        },
        "data_type": v.data_type,
        "source_model": v.source_model,
        "source_field": v.source_field,
        "choice_list": v.choice_list,
        "choice_kind": v.choice_kind,
        "privacy_class": {
            "code": v.privacy_class.code,
            "label": v.privacy_class.label,
            "k_floor": v.privacy_class.k_floor,
        },
        "status": v.status,
        "questionnaire_section": v.questionnaire_section,
        "has_completeness_baseline": v.has_completeness_baseline,
        "synonyms": v.synonyms,
        "version": v.version,
    }


def _serialise_privacy_class(pc) -> dict:
    return {
        "id": str(pc.id),
        "code": pc.code,
        "label": pc.label,
        "description": pc.description,
        "k_floor": pc.k_floor,
        "daily_user_cap": pc.daily_user_cap,
        "daily_org_cap": pc.daily_org_cap,
        "blocks_aggregate": pc.blocks_aggregate,
    }


# ---------------------------------------------------------------------------
# Audit helper — every endpoint, every response code.

def _emit(action: str, *, actor: str, entity_type: str = "data_explorer",
          entity_id: str = "", reason: str = "", request=None,
          field_changes: dict | None = None) -> None:
    emit_audit(
        action, entity_type, entity_id or "n/a",
        actor=actor or "anonymous",
        reason=reason,
        field_changes=field_changes,
        ip_address=_client_ip(request) if request is not None else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")
                    if request is not None else ""),
    )


def _actor(request) -> str:
    """Return the audit actor id. We use the Django user PK so the
    AuditEvent.actor_id column joins on `auth_user.id`; the username
    is captured separately in reason when useful. Falls back to
    "anonymous" for unauthenticated requests (which the permission
    layer should already block, but defensively)."""
    u = getattr(request, "user", None)
    if u is None or not getattr(u, "is_authenticated", False):
        return "anonymous"
    return str(getattr(u, "id", "") or getattr(u, "pk", "") or "anonymous")


def _org_code(request) -> str:
    """Resolve the requesting user's org code for the org-cap counter.
    Until partner-affiliation lives on User, this falls back to the
    username for org-of-one tracking; superusers get 'NSR'."""
    u = getattr(request, "user", None)
    if u is None:
        return ""
    if getattr(u, "is_superuser", False):
        return "NSR"
    # Hook point for the Keycloak adapter — read org from user.profile
    # once that lands.
    return getattr(u, "username", "")


# ---------------------------------------------------------------------------
# Catalogue viewsets

class DatasetViewSet(viewsets.ViewSet):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def list(self, request):
        rows = MetadataCatalog.list_datasets(user=request.user)
        data = [_serialise_dataset(d) for d in rows]
        _emit("data_explorer.catalogue.browsed",
              actor=_actor(request), entity_type="Dataset",
              reason=f"count={len(data)}",
              field_changes={"result_count": len(data)},
              request=request)
        return Response({"results": data, "count": len(data)})

    def retrieve(self, request, pk: str | None = None):
        ds = MetadataCatalog.get_dataset(pk)
        if ds is None:
            _emit("data_explorer.dataset.read", actor=_actor(request),
                  entity_type="Dataset",
                  entity_id=pk or "", reason="not_found",
                  field_changes={"dataset_code": pk or ""},
                  request=request)
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        _emit("data_explorer.dataset.read", actor=_actor(request),
              entity_type="Dataset",
              entity_id=str(ds.id), reason=ds.code,
              field_changes={"dataset_code": ds.code},
              request=request)
        return Response(_serialise_dataset(ds))

    @action(detail=True, methods=["get"], url_path="variables")
    def variables(self, request, pk: str | None = None):
        ds = MetadataCatalog.get_dataset(pk)
        if ds is None:
            _emit("data_explorer.dataset.variables.read",
                  actor=_actor(request), entity_id=pk or "",
                  reason="not_found", request=request)
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        include_inactive = request.query_params.get(
            "include_inactive", "0",
        ) in ("1", "true", "yes")
        rows = MetadataCatalog.list_variables(
            dataset_code=ds.code,
            include_inactive=include_inactive,
        )
        data = [_serialise_variable(v) for v in rows]
        _emit("data_explorer.dataset.variables.read",
              actor=_actor(request), entity_id=str(ds.id),
              reason=f"count={len(data)} include_inactive={include_inactive}",
              request=request)
        return Response({"results": data, "count": len(data)})


class VariableViewSet(viewsets.ViewSet):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def list(self, request):
        q = request.query_params.get("q")
        privacy_class = request.query_params.get("privacy_class")
        dataset = request.query_params.get("dataset")
        baseline_param = request.query_params.get("has_completeness_baseline")
        baseline = None
        if baseline_param is not None:
            baseline = baseline_param in ("1", "true", "yes")
        include_inactive = request.query_params.get(
            "include_inactive", "0",
        ) in ("1", "true", "yes")
        rows = MetadataCatalog.list_variables(
            dataset_code=dataset,
            include_inactive=include_inactive,
            privacy_class=privacy_class,
            q=q,
            has_completeness_baseline=baseline,
        )
        data = [_serialise_variable(v) for v in rows]
        _emit("data_explorer.variable.searched",
              actor=_actor(request),
              entity_type="variable_catalogue",
              reason=(
                  f"q={q!r} class={privacy_class!r} ds={dataset!r} "
                  f"baseline={baseline} include_inactive={include_inactive}"
              ),
              request=request)
        return Response({"results": data, "count": len(data)})

    def retrieve(self, request, pk: str | None = None):
        # Inactive variables 404 — the catalogue is read-only and
        # INACTIVE rows haven't been dual-approved yet.
        include_inactive = request.query_params.get(
            "include_inactive", "0",
        ) in ("1", "true", "yes")
        v = MetadataCatalog.get_variable(pk, include_inactive=include_inactive)
        if v is None:
            _emit("data_explorer.variable.read", actor=_actor(request),
                  entity_type="Variable",
                  entity_id=pk or "", reason="not_found",
                  field_changes={"variable_code": pk or ""},
                  request=request)
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        out = _serialise_variable(v)
        # Lineage stub — the field's questionnaire section and its
        # ChoiceList. Full lineage (form question, DDI metadata) is
        # OPEN; this is the discoverable subset.
        out["lineage"] = {
            "questionnaire_section": v.questionnaire_section,
            "source_model": v.source_model,
            "source_field": v.source_field,
            "choice_list": v.choice_list,
        }
        # Related = same-dataset variables in the same privacy class.
        related = MetadataCatalog.list_variables(
            dataset_code=v.dataset.code,
        )
        out["related"] = [
            {"id": str(r.id), "code": r.code, "label": r.label}
            for r in related if r.id != v.id and r.privacy_class_id == v.privacy_class_id
        ][:10]
        _emit("data_explorer.variable.read",
              actor=_actor(request), entity_type="Variable",
              entity_id=str(v.id), reason=v.code,
              field_changes={"variable_code": v.code},
              request=request)
        return Response(out)


class PrivacyClassListView(APIView):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def get(self, request):
        rows = MetadataCatalog.list_privacy_classes()
        data = [_serialise_privacy_class(pc) for pc in rows]
        _emit("data_explorer.privacy_classes.read",
              actor=_actor(request),
              entity_type="PrivacyClass",
              reason=f"count={len(data)}",
              field_changes={"result_count": len(data)},
              request=request)
        # ADR-0023 §D8: the `Aggregated-only` badge maps to the system
        # accent token (catalogue cards whose PrivacyClass disallows
        # record-level discovery from the Explorer). Shipped on the
        # /privacy-classes payload so the UI has zero hardcoded
        # labels / colours.
        return Response({
            "results": data,
            "count": len(data),
            "aggregated_only_badge": {
                "code": "aggregated_only",
                "label": "Aggregated-only",
                "token_fg": "var(--accent-system)",  # nosec B105 - CSS design token, not a secret
                "token_bg": "var(--accent-system-bg)",  # nosec B105 - CSS design token, not a secret
            },
        })


class SuppressionVocabularyView(APIView):
    """ADR-0023 §D8: the `Suppressed` cell badge maps to the neutral
    token. Lives on its own endpoint so the aggregate-builder can
    fetch it once at mount without conflating it with the
    PrivacyClass catalogue."""

    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def get(self, request):
        return Response({
            "suppressed": {
                "code": "suppressed",
                "label": "Suppressed",
                "token_fg": "var(--neutral-700)",  # nosec B105 - CSS design token, not a secret
                "token_bg": "var(--neutral-100)",  # nosec B105 - CSS design token, not a secret
                "tooltip": (
                    "Count below privacy floor — see ADR-0023 for details."
                ),
            },
        })


# ---------------------------------------------------------------------------
# Aggregate endpoint — the suppressor funnel.

class AggregateView(APIView):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def post(self, request):
        payload = request.data or {}
        actor = _actor(request)
        org_code = _org_code(request)
        try:
            validated = validate(payload)
        except ValidationError as e:
            # Look up the dataset so the audit + response can carry
            # the dataset entity_id even on geographic-floor refusals.
            ds_code = payload.get("dataset") or payload.get("dataset_code")
            ds_id = ""
            if ds_code:
                from .models import Dataset
                ds_row = Dataset.objects.filter(code=ds_code).first()
                if ds_row is not None:
                    ds_id = str(ds_row.id)

            geo = payload.get("geographic_scope") or {}
            extras = dict(e.extras or {})
            if e.code == "geographic_floor_violation":
                # UI needs the original intent so it can render the
                # "Request record-level data — <scope_label> → <level>" CTA.
                extras.setdefault("requested_level", geo.get("level"))
                extras.setdefault("requested_codes", geo.get("codes") or [])
                extras.setdefault(
                    "scope_label",
                    ",".join(geo.get("codes") or []) or geo.get("level", ""),
                )
                extras.setdefault("handoff", "/api/v1/data-requests/draft/")

            _emit(
                action=(
                    "data_explorer.aggregate.refused_below_floor"
                    if e.code == "geographic_floor_violation" else
                    "data_explorer.aggregate.rejected"
                ),
                actor=actor,
                entity_type="Dataset",
                entity_id=ds_id,
                reason=f"{e.code}: {e.detail}",
                field_changes={
                    "code": e.code,
                    "dataset_code": ds_code or "",
                    **extras,
                },
                request=request,
            )
            body = {"error": e.code, "detail": e.detail, **extras}
            return Response(body, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Stash the filter payload so the query builder can apply it
        # without re-parsing.
        validated.filter_payload = payload.get("filters") or {}

        # Throttle gate — only after validation so we don't burn quota
        # on a malformed payload. The throttle service emits
        # `data_explorer.throttle.exceeded` itself with entity_type=User,
        # so we don't double-audit here.
        try:
            PrivacyClassThrottle.check_and_increment(
                actor=actor, org_code=org_code,
                privacy_class=validated.strictest_class,
                raise_on_deny=True,
            )
        except Throttled as t:
            d = t.decision
            resp = Response(
                {
                    "error": "throttled",
                    "detail": d.reason,
                    "retry_after_seconds": d.retry_after_seconds,
                    "privacy_class": validated.strictest_class.code,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            resp["Retry-After"] = str(d.retry_after_seconds)
            return resp

        try:
            result = AggregateQueryService.execute(
                validated_query=validated,
            )
        except StaleMatviewError as e:
            _emit(
                "data_explorer.matview.stale",
                actor=actor,
                entity_type="Dataset",
                entity_id=str(validated.dataset.id),
                reason=str(e),
                field_changes={
                    "matview": e.matview,
                    "refreshed_at": (
                        e.refreshed_at.isoformat() if e.refreshed_at else None
                    ),
                    "staleness_seconds": e.staleness_seconds,
                    "cadence": e.max_seconds,
                    "max_seconds": e.max_seconds,
                },
                request=request,
            )
            return Response(
                {
                    "error": "matview_stale",
                    "matview": e.matview,
                    "refreshed_at": (
                        e.refreshed_at.isoformat() if e.refreshed_at else None
                    ),
                    "staleness_seconds": e.staleness_seconds,
                    "max_seconds": e.max_seconds,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Persist the log row + emit the success audit.
        write_query_log(
            actor=actor, dataset=validated.dataset,
            validated_query=validated, result=result,
        )
        _emit(
            "data_explorer.aggregate.executed",
            actor=actor,
            entity_type="Dataset",
            entity_id=str(validated.dataset.id),
            reason=(
                f"dataset={validated.dataset.code} "
                f"rows={result.total_cell_count} "
                f"suppressed={result.suppressed_cell_count}"
            ),
            field_changes={
                "dataset": validated.dataset.code,
                "matview": result.matview,
                "refreshed_at": (
                    result.refreshed_at.isoformat()
                    if getattr(result, "refreshed_at", None) else None
                ),
                "strictest_class": result.strictest_class,
                "rows": result.total_cell_count,
                "suppressed_cell_count": result.suppressed_cell_count,
                "query_hash": result.query_hash,
                "filter_hash": result.filter_hash,
            },
            request=request,
        )

        return Response({
            "rows": result.rows,
            "metadata": {
                "matview": result.matview,
                "refreshed_at": (
                    result.refreshed_at.isoformat()
                    if result.refreshed_at else None
                ),
                "staleness_seconds": result.staleness_seconds,
                "suppressed_cell_count": result.suppressed_cell_count,
                "total_cell_count": result.total_cell_count,
                "k_floor": result.k_floor,
                "strictest_privacy_class": result.strictest_class,
                "query_hash": result.query_hash,
                "filter_hash": result.filter_hash,
            },
        })


# ---------------------------------------------------------------------------
# Coverage endpoint

class CoverageView(APIView):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def get(self, request, dataset_id: str | None = None):
        ds = MetadataCatalog.get_dataset(dataset_id)
        if ds is None:
            _emit("data_explorer.coverage.read", actor=_actor(request),
                  entity_id=dataset_id or "", reason="dataset_not_found",
                  request=request)
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        from .models import CoverageSnapshot
        rows = list(
            CoverageSnapshot.objects
            .filter(dataset=ds)
            .order_by("-captured_at", "geo_level", "geo_code")[:500]
        )
        data = [
            {
                "geo_level": r.geo_level,
                "geo_code": r.geo_code,
                "geo_label": r.geo_label,
                "completeness_pct": float(r.completeness_pct),
                "row_count": r.row_count,
                "captured_at": r.captured_at.isoformat(),
            }
            for r in rows
        ]
        _emit("data_explorer.coverage.read", actor=_actor(request),
              entity_id=str(ds.id), reason=f"count={len(data)}",
              request=request)
        return Response({
            "dataset": _serialise_dataset(ds),
            "results": data,
            "count": len(data),
        })


# ---------------------------------------------------------------------------
# Synthetic sample — for UI preview. Never real records.

class SyntheticSampleView(APIView):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    def get(self, request, dataset_id: str | None = None):
        ds = MetadataCatalog.get_dataset(dataset_id)
        if ds is None:
            _emit("data_explorer.synthetic_sample.read",
                  actor=_actor(request), entity_id=dataset_id or "",
                  reason="dataset_not_found", request=request)
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        # Deterministic synthetic — three rows per matview shape. The
        # field values mirror the matview columns but are clearly
        # placeholder.
        variables = MetadataCatalog.list_variables(dataset_code=ds.code)
        sample = []
        for i in range(3):
            row = {"_synthetic": True, "row": i + 1}
            for v in variables:
                if v.data_type == "number":
                    row[v.code] = i * 10
                elif v.data_type == "boolean":
                    row[v.code] = bool(i % 2)
                elif v.data_type == "select":
                    row[v.code] = f"opt_{(i % 3) + 1}"
                else:
                    row[v.code] = f"sample-{v.code}-{i + 1}"
            sample.append(row)
        _emit("data_explorer.synthetic_sample.read",
              actor=_actor(request), entity_id=str(ds.id),
              reason=f"rows={len(sample)}", request=request)
        return Response({
            "dataset": _serialise_dataset(ds),
            "rows": sample,
            "warning": (
                "Synthetic placeholders for UI preview only. Not "
                "from the registry."
            ),
        })


# ---------------------------------------------------------------------------
# Handoff endpoint — DATA-EXP → API-DRS draft seeder.

class HandoffView(APIView):
    permission_classes = [IsExplorerRoleAndFlagEnabled]

    # purpose_of_use + requested_entity are always required.
    # dsa_id is required UNLESS the call rides on an explorer session
    # whose prior aggregate already carries the DSA context.
    BASE_REQUIRED = ("purpose_of_use", "requested_entity")

    def post(self, request):
        payload = request.data or {}
        actor = _actor(request)
        # Session-driven handoff (Tester contract): accept `session_id`
        # and pull aggregate context off the ExplorerSession row.
        session_id = (
            payload.get("session_id")
            or payload.get("explorer_session_id")
        )
        missing = [k for k in self.BASE_REQUIRED if not payload.get(k)]
        if not session_id and not payload.get("dsa_id"):
            missing.append("dsa_id_or_session_id")
        if missing:
            _emit(
                "data_explorer.handoff.rejected",
                actor=actor, entity_type="DataRequest", entity_id="",
                reason=f"missing={missing}", request=request,
                field_changes={"missing": missing},
            )
            return Response(
                {"error": "bad_payload", "missing": missing},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        try:
            res = perform_handoff(
                actor=actor,
                dsa_id=payload.get("dsa_id") or "",
                purpose_of_use=payload["purpose_of_use"],
                requested_entity=payload["requested_entity"],
                requested_fields=payload.get("requested_fields") or [],
                geographic_scope=payload.get("geographic_scope") or {},
                filter_expression=payload.get("filter_expression") or {},
                estimated_row_count=int(
                    payload.get("estimated_row_count") or 0,
                ),
                source_query_hash=payload.get("source_query_hash") or "",
                explorer_session_id=session_id,
                requester_note=payload.get("requester_note") or "",
            )
        except Exception as exc:  # noqa: BLE001 — surface as 422
            _emit(
                "data_explorer.handoff.rejected",
                actor=actor, entity_type="DataRequest", entity_id="",
                reason=str(exc), request=request,
                field_changes={"detail": str(exc)},
            )
            return Response(
                {"error": "handoff_failed", "detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # source_query_hash may come from the payload OR from the
        # ExplorerSession (the wizard binds it on first aggregate).
        # Resolve fresh after handoff so the audit row has it
        # regardless of which side carried it.
        resolved_query_hash = payload.get("source_query_hash") or ""
        if not resolved_query_hash and res.explorer_session_id:
            from .models import ExplorerSession
            _s = ExplorerSession.objects.filter(
                id=res.explorer_session_id,
            ).first()
            if _s is not None:
                resolved_query_hash = _s.last_query_hash or ""
        _emit(
            "data_explorer.handoff.created",
            actor=actor,
            entity_type="DataRequest",
            entity_id=res.data_request_id,
            reason=f"session={res.explorer_session_id}",
            field_changes={
                "data_request_id": res.data_request_id,
                "explorer_session_id": res.explorer_session_id,
                "source_query_hash": resolved_query_hash,
                "purpose_of_use": payload["purpose_of_use"][:255],
            },
            request=request,
        )
        return Response(
            {
                "data_request_id": res.data_request_id,
                # UI expects `redirect` per ADR §sequence-c; the URL
                # form is preserved as `redirect_url` for any older
                # caller that already wires it.
                "redirect": res.redirect_url,
                "redirect_url": res.redirect_url,
                "explorer_session_id": res.explorer_session_id,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Public questionnaire-transparency catalogue

class PublicCatalogueView(APIView):
    """GET /api/v1/data-explorer/catalogue/public/ — anonymous, read-only
    data dictionary of the ENTIRE questionnaire so the public can see
    what the registry captures (ADR-0023 public-discovery extension).

    Metadata only: field id, label, type, questionnaire section, privacy
    class, and whether the field is ever aggregatable. No household
    records, no cell counts. Still subject to the DATA_EXPLORER_ENABLED
    kill-switch (off → 503), but no role/auth is required."""

    permission_classes = [FlagEnabledPublic]

    def get(self, request):
        from . import public_catalogue

        body = public_catalogue.build()
        _emit(
            "data_explorer.public_catalogue.browsed",
            actor=_actor(request),
            entity_type="questionnaire_catalogue",
            reason=(
                f"sections={body['totals']['sections']} "
                f"fields={body['totals']['fields']}"
            ),
            request=request,
        )
        return Response(body)


__all__ = [
    "AggregateView",
    "CoverageView",
    "DatasetViewSet",
    "HandoffView",
    "PrivacyClassListView",
    "PublicCatalogueView",
    "SyntheticSampleView",
    "VariableViewSet",
]
