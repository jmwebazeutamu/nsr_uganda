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

from .audit import emit, stored_reason


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



# How long an identical list read is treated as the same visit.
#
# The console polls five endpoints for its sidebar badges about every
# 30 seconds. On this database that produced 124,285 of 137,187 audit
# rows — 91% of the chain was one browser tab counting things, roughly
# 24,000 rows on each of stage_record, change_request, data_request,
# grievance and match_pair. An audit trail nobody can read is not an
# audit trail, and verifying it costs the same whether the rows mean
# anything or not.
#
# Deduped rather than dropped, and deduped SERVER-side. A client header
# saying "do not audit this one" would let any caller opt out of the
# record of their own access to personal data.
AUDIT_LIST_READ_DEDUPE_SECONDS = 300


def _dedupe_window_seconds() -> int:
    from django.conf import settings

    return int(getattr(
        settings, "AUDIT_LIST_READ_DEDUPE_SECONDS",
        AUDIT_LIST_READ_DEDUPE_SECONDS,
    ))



def _is_plain_list_request(request) -> bool:
    """True when the whole request is captured by what gets logged.

    The dedupe matches on the stored `reason`, which projects only
    _AUDIT_REASON_QUERY_KEYS. A request carrying anything outside that
    set — a status filter, a search term — is not described by the row
    it would match against, so collapsing it would hide a genuinely
    different read behind an earlier one.

    The console's badge poller sends `page_size` alone, so polls still
    collapse; an operator narrowing a list does not.
    """
    if not hasattr(request, "query_params"):
        return True
    return all(
        key in _AUDIT_REASON_QUERY_KEYS
        for key, value in request.query_params.items()
        if value
    )


def _is_repeat_read(
    *, action: str, actor: str, entity_type: str, reason: str,
    entity_id: str | None = None,
) -> bool:
    """True when this exact read was already recorded recently.

    Matched on actor + entity_type + reason (+ entity_id for a
    single-record read), and `reason` carries the request's filters —
    so a poller repeating one URL collapses, while an operator changing
    a filter is a different read and is recorded. The first call in
    each window is always written, so the access itself is never
    invisible.

    `action` is a parameter because the same problem arrived a second
    time. The list dedupe was written when a badge poller turned 91% of
    the chain into one browser tab counting things; the GRM case panel
    then began reading one grievance's audit chain every time the
    operator moved down the queue. Same shape, same window, so the same
    rule rather than a second one beside it.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.security.models import AuditEvent

    since = timezone.now() - timedelta(seconds=_dedupe_window_seconds())
    qs = AuditEvent.objects.filter(
        action=action,
        actor_id=actor,
        entity_type=entity_type,
        reason=reason,
        occurred_at__gte=since,
    )
    if entity_id is not None:
        qs = qs.filter(entity_id=entity_id)
    return qs.exists()


def _is_repeat_list_read(*, actor: str, entity_type: str, reason: str) -> bool:
    """Back-compat name for the list case."""
    return _is_repeat_read(
        action="list_read", actor=actor, entity_type=entity_type,
        reason=reason,
    )


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

    def _emit_read(self, request, *, action: str, entity_id: str,
                   dedupe: bool = False) -> None:
        """`dedupe=True` collapses a repeat read of the SAME record by
        the same actor inside the window — for a surface the operator
        re-enters as they move around, rather than one they visit once.
        Different records are always different reads, so moving down a
        queue still leaves one row per case."""
        user = getattr(request, "user", None)
        actor = (
            getattr(user, "username", "") or "anonymous"
            if user is not None else "anonymous"
        )
        from apps.security.purpose import resolve_purpose

        reason = _build_reason(request)
        purpose = resolve_purpose(request, self)
        entity_type = self.audit_entity_type or getattr(self, "basename", "unknown")
        # The STORED form — emit folds the purpose into reason, so
        # matching the pre-fold value matches nothing.
        stored = stored_reason(reason, purpose)
        if action == "list_read" and _is_plain_list_request(request) \
                and _is_repeat_read(
            action=action, actor=actor, entity_type=entity_type, reason=stored,
        ):
            return
        if dedupe and action != "list_read" and _is_repeat_read(
            action=action, actor=actor, entity_type=entity_type,
            reason=stored, entity_id=entity_id,
        ):
            return

        emit(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            actor_kind="user",
            reason=reason,
            # Why this record was read. Declared by the viewset via
            # access_purpose / access_purpose_map; "" when undeclared.
            purpose=purpose,
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
