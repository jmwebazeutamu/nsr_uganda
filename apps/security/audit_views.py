"""DRF viewset mixin that emits an AuditEvent on every read of personal data.

SAD §8.4: "Every read of personal data is logged: actor, action,
household ID, member ID, fields, IP, user agent, timestamp." DPIA §8
makes the same claim. Until this mixin is on every personal-data viewset
the claim is paper-only.

Per ADR-0001 cross-app shared service: every app that exposes personal
data imports this mixin and applies it to the relevant viewsets. The
mixin is a no-op for response status >= 400 so refused reads don't
inflate the chain.

Anomaly detection on read patterns (threat model T1) consumes the rows
this mixin writes; the volume signal lives in action='list_read' rows.
"""

from __future__ import annotations

from .audit import emit


def _client_ip(request) -> str | None:
    """Trust X-Forwarded-For only when behind the Kong gateway (Sprint 2
    deployment story). For now, fall back to REMOTE_ADDR — Django's
    default — so dev requests get a real IP."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR")


# US-S16-001 — query params we lift into AuditEvent.reason so DPO
# anomaly sampling has structured context without re-parsing URLs.
# Kept narrow: scope-narrowing filters (sub_region_code, household_id,
# entity_id) + the pagination knobs page/page_size. Add a param here
# only when the DPO has a reason to sample on it.
_AUDIT_REASON_QUERY_KEYS = (
    "sub_region_code",
    "household_id",
    "entity_id",
    "page",
    "page_size",
)


def _build_reason(request) -> str:
    """Project the subset of request.query_params we want in the
    AuditEvent.reason string. Returns "" when none of the keys are
    present (audit row stays clean for the common case)."""
    if not hasattr(request, "query_params"):
        return ""
    parts = []
    for k in _AUDIT_REASON_QUERY_KEYS:
        v = request.query_params.get(k)
        if v:
            parts.append(f"{k}={v}")
    return " ".join(parts)


class AuditReadMixin:
    """Apply to DRF ReadOnlyModelViewSet / ModelViewSet subclasses that
    expose personal data. Emits action='read' on retrieve and
    action='list_read' on list. Override `audit_entity_type` to control
    the entity_type label in the AuditEvent."""

    audit_entity_type = ""

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if response.status_code < 400:
            self._emit_read(
                request,
                action="read",
                entity_id=str(kwargs.get("pk", "")),
            )
        return response

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if response.status_code < 400:
            data = getattr(response, "data", None)
            if isinstance(data, dict):
                count = data.get("count", len(data.get("results", []) or []))
            elif isinstance(data, list):
                count = len(data)
            else:
                count = 0
            page = request.query_params.get("page", "1") if hasattr(request, "query_params") else "1"
            self._emit_read(
                request,
                action="list_read",
                entity_id=f"page={page} size={count}",
            )
        return response

    def _emit_read(self, request, *, action: str, entity_id: str) -> None:
        user = getattr(request, "user", None)
        actor = (
            getattr(user, "username", "") or "anonymous"
            if user is not None else "anonymous"
        )
        emit(
            action=action,
            entity_type=self.audit_entity_type or getattr(self, "basename", "unknown"),
            entity_id=entity_id,
            actor=actor,
            actor_kind="user",
            reason=_build_reason(request),
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
