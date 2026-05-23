"""Admin Console — Reference Data API (Cat 1: Choice lists + Geography).

Mounted under /api/v1/admin/refdata/. Gated on IsAdminConsoleUser. All
write paths route through the lifecycle / versioned-write services in
apps.reference_data so audit emission and no-self-approve rules can't
be bypassed.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404
from rest_framework import status as drf_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.admin_console.permissions import IsAdminConsoleUser
from apps.reference_data import lifecycle
from apps.reference_data.models import (
    ChoiceList,
    ChoiceListStatus,
    ChoiceOption,
    GeographicUnit,
)
from apps.reference_data.usage_registry import field_paths_for
from apps.security.audit import emit as emit_audit

# ───────────────────────────────────────────────────────────────
# Choice Lists
# ───────────────────────────────────────────────────────────────

def _list_summary_row(list_name: str, rows: list[ChoiceList]) -> dict:
    """Collapse all versions of one list_name into a single row for
    the list view."""
    active = next((r for r in rows if r.status == ChoiceListStatus.ACTIVE), None)
    draft = next((r for r in rows if r.status == ChoiceListStatus.DRAFT), None)
    options_count = 0
    if active:
        options_count = ChoiceOption.objects.filter(
            choice_list=active,
            status=ChoiceOption.Status.ACTIVE,
        ).count()
    last_updated = max((r.updated_at for r in rows), default=None)
    return {
        "list_name": list_name,
        "active_version": active.version if active else None,
        "active_id": active.id if active else None,
        "draft_version": draft.version if draft else None,
        "draft_id": draft.id if draft else None,
        "options_count": options_count,
        "is_pii_classified": bool(active and active.is_pii_classified),
        "last_updated": last_updated.isoformat() if last_updated else None,
        "uses": field_paths_for(list_name),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAdminConsoleUser])
def choice_lists(request):
    """GET — collapsed list view (one row per list_name).
    POST — create a new DRAFT for a new list_name.
    """
    if request.method == "GET":
        all_lists = list(
            ChoiceList.objects
            .all()
            .order_by("list_name", "-version")
        )
        grouped: dict[str, list[ChoiceList]] = {}
        for cl in all_lists:
            grouped.setdefault(cl.list_name, []).append(cl)
        results = [_list_summary_row(name, rows) for name, rows in sorted(grouped.items())]
        return Response({"results": results, "count": len(results)})

    # POST
    body = request.data or {}
    list_name = (body.get("list_name") or "").strip()
    if not list_name:
        return Response(
            {"detail": "list_name is required"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    if ChoiceList.objects.filter(list_name=list_name).exists():
        return Response(
            {"detail": f"list_name '{list_name}' already exists — use /clone/ instead"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    cl = ChoiceList.objects.create(
        list_name=list_name,
        version=1,
        description=body.get("description", ""),
        status=ChoiceListStatus.DRAFT,
        author=body.get("author") or request.user.username,
        is_pii_classified=bool(body.get("is_pii_classified", False)),
    )
    emit_audit(
        action="choicelist.created",
        entity_type="reference_data.choice_list",
        entity_id=cl.id,
        actor=cl.author,
        reason=f"list_name={list_name} v1",
    )
    return Response(_version_detail(cl), status=drf_status.HTTP_201_CREATED)


def _version_detail(cl: ChoiceList) -> dict:
    return {
        "id": cl.id,
        "list_name": cl.list_name,
        "version": cl.version,
        "status": cl.status,
        "description": cl.description,
        "author": cl.author,
        "approved_by": cl.approved_by,
        "approved_at": cl.approved_at.isoformat() if cl.approved_at else None,
        "submitted_at": cl.submitted_at.isoformat() if cl.submitted_at else None,
        "rejection_reason": cl.rejection_reason,
        "is_pii_classified": cl.is_pii_classified,
        "options": [
            {
                "code": o.code,
                "label": o.label,
                "language": o.language,
                "parent_code": o.parent_code,
                "sort_order": o.sort_order,
                "status": o.status,
            }
            for o in cl.options.order_by("sort_order", "code", "language")
        ],
        "uses": field_paths_for(cl.list_name),
    }


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def choice_list_versions(request, list_name: str):
    rows = list(
        ChoiceList.objects
        .filter(list_name=list_name)
        .order_by("-version")
    )
    if not rows:
        raise Http404(f"no ChoiceList named {list_name!r}")
    return Response({
        "list_name": list_name,
        "versions": [
            {
                "id": cl.id,
                "version": cl.version,
                "status": cl.status,
                "author": cl.author,
                "approved_by": cl.approved_by,
                "approved_at": cl.approved_at.isoformat() if cl.approved_at else None,
                "options_count": cl.options.filter(status=ChoiceOption.Status.ACTIVE).count(),
                "updated_at": cl.updated_at.isoformat(),
            }
            for cl in rows
        ],
        "is_pii_classified": any(r.is_pii_classified for r in rows),
        "uses": field_paths_for(list_name),
    })


def _get_version(list_name: str, version: int) -> ChoiceList:
    try:
        return ChoiceList.objects.get(list_name=list_name, version=version)
    except ChoiceList.DoesNotExist as e:
        raise Http404(f"{list_name} v{version}") from e


@api_view(["GET", "POST"])
@permission_classes([IsAdminConsoleUser])
def choice_list_options(request, list_name: str, version: int):
    cl = _get_version(list_name, int(version))
    if request.method == "GET":
        return Response(_version_detail(cl))

    # POST — add an option (DRAFT only)
    if cl.status != ChoiceListStatus.DRAFT:
        return Response(
            {"detail": "options can only be added to a DRAFT version — clone to a draft first"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    body = request.data or {}
    code = (body.get("code") or "").strip()
    label = (body.get("label") or "").strip()
    if not code or not label:
        return Response(
            {"detail": "code and label are required"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    language = body.get("language", "en")
    if ChoiceOption.objects.filter(
        choice_list=cl, code=code, language=language,
    ).exists():
        return Response(
            {"detail": f"option code={code!r} language={language!r} already exists"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    opt = ChoiceOption.objects.create(
        choice_list=cl,
        code=code,
        label=label,
        language=language,
        parent_code=body.get("parent_code", ""),
        sort_order=body.get("sort_order", 0),
    )
    emit_audit(
        action="choiceoption.added",
        entity_type="reference_data.choice_option",
        entity_id=opt.id,
        actor=request.user.username,
        reason=f"list={list_name} v{version} code={code}",
        field_changes={"code": code, "label": label, "language": language},
    )
    return Response(_version_detail(cl), status=drf_status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAdminConsoleUser])
def choice_list_option_detail(
    request, list_name: str, version: int, code: str,
):
    if request.method == "DELETE":
        return Response(
            {"detail": "ChoiceOption deletion is forbidden — use PATCH with status='deprecated' instead"},
            status=drf_status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    cl = _get_version(list_name, int(version))
    if cl.status != ChoiceListStatus.DRAFT:
        return Response(
            {"detail": "options can only be edited on a DRAFT version — clone to a draft first"},
            status=drf_status.HTTP_409_CONFLICT,
        )
    language = request.query_params.get("language", "en")
    try:
        opt = ChoiceOption.objects.get(
            choice_list=cl, code=code, language=language,
        )
    except ChoiceOption.DoesNotExist as e:
        raise Http404(f"option code={code} language={language}") from e

    body = request.data or {}
    if body.get("status") == "deprecated":
        lifecycle.deprecate_option(
            opt,
            actor=request.user.username,
            reason=body.get("reason", ""),
        )
        return Response(_version_detail(cl))

    before = {
        "label": opt.label,
        "sort_order": opt.sort_order,
        "parent_code": opt.parent_code,
    }
    for field in ("label", "sort_order", "parent_code"):
        if field in body:
            setattr(opt, field, body[field])
    opt.save(update_fields=["label", "sort_order", "parent_code", "updated_at"])
    emit_audit(
        action="choiceoption.edited",
        entity_type="reference_data.choice_option",
        entity_id=opt.id,
        actor=request.user.username,
        reason=f"list={list_name} v{version} code={code}",
        field_changes={"before": before, "after": {
            "label": opt.label,
            "sort_order": opt.sort_order,
            "parent_code": opt.parent_code,
        }},
    )
    return Response(_version_detail(cl))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def choice_list_clone(request, list_name: str):
    """Clone the latest version of `list_name` into a new DRAFT."""
    src = (
        ChoiceList.objects
        .filter(list_name=list_name)
        .order_by("-version")
        .first()
    )
    if src is None:
        raise Http404(f"no ChoiceList named {list_name!r}")
    draft = lifecycle.clone_to_draft(src, author=request.user.username)
    return Response(_version_detail(draft), status=drf_status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def choice_list_submit(request, list_name: str, version: int):
    cl = _get_version(list_name, int(version))
    try:
        lifecycle.submit_for_approval(cl, actor=request.user.username)
    except lifecycle.ChoiceListApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_version_detail(cl))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def choice_list_sign(request, list_name: str, version: int):
    cl = _get_version(list_name, int(version))
    body = request.data or {}
    approver = (body.get("approver") or request.user.username or "").strip()
    note = body.get("note", "")
    try:
        lifecycle.sign(
            cl,
            approver=approver,
            note=note,
            actor=request.user.username,
        )
    except lifecycle.ChoiceListApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_version_detail(cl))


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def choice_list_reject(request, list_name: str, version: int):
    cl = _get_version(list_name, int(version))
    body = request.data or {}
    approver = (body.get("approver") or request.user.username or "").strip()
    reason = body.get("reason", "")
    try:
        lifecycle.reject(
            cl,
            approver=approver,
            reason=reason,
            actor=request.user.username,
        )
    except lifecycle.ChoiceListApprovalError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_version_detail(cl))


# ───────────────────────────────────────────────────────────────
# Geography
# ───────────────────────────────────────────────────────────────

_LEVEL_ORDER = ("region", "sub_region", "district", "county", "sub_county", "parish", "village")


def _geo_row(unit: GeographicUnit) -> dict:
    return {
        "id": unit.id,
        "level": unit.level,
        "code": unit.code,
        "name": unit.name,
        "parent_id": unit.parent_id,
        "parent_code": unit.parent.code if unit.parent else None,
        "status": unit.status,
        "effective_from": unit.effective_from.isoformat() if unit.effective_from else None,
        "effective_to": unit.effective_to.isoformat() if unit.effective_to else None,
        "children_count": unit.children_count_cached,
        "households_count": unit.households_count_cached,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAdminConsoleUser])
def geography_collection(request):
    """GET — drill list. POST — create a new unit at the requested level."""
    if request.method == "GET":
        level = request.query_params.get("level", "region")
        parent_code = request.query_params.get("parent_code", "")
        include_inactive = request.query_params.get("include_inactive", "").lower() in (
            "true", "1", "yes",
        )
        if level not in _LEVEL_ORDER:
            return Response(
                {"detail": f"unknown level {level!r}"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        qs = GeographicUnit.objects.filter(level=level)
        if parent_code:
            qs = qs.filter(parent__code=parent_code)
        if not include_inactive:
            qs = qs.filter(status=GeographicUnit.Status.ACTIVE)
        qs = qs.order_by("code")
        return Response({
            "level": level,
            "parent_code": parent_code,
            "results": [_geo_row(u) for u in qs.select_related("parent")],
        })

    # POST — new unit
    body = request.data or {}
    level = body.get("level")
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    parent_code = body.get("parent_code") or ""
    effective_from = body.get("effective_from") or date.today().isoformat()

    if not (level and code and name):
        return Response(
            {"detail": "level, code, and name are required"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )
    if level not in _LEVEL_ORDER:
        return Response(
            {"detail": f"unknown level {level!r}"},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )

    parent = None
    if parent_code:
        parent = GeographicUnit.objects.filter(
            code=parent_code, status=GeographicUnit.Status.ACTIVE,
        ).first()
        if parent is None:
            return Response(
                {"detail": f"parent_code {parent_code!r} not found or not active"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

    if GeographicUnit.objects.filter(
        level=level, code=code, status=GeographicUnit.Status.ACTIVE,
    ).exists():
        return Response(
            {"detail": f"{level} {code!r} already exists — use PATCH to replace"},
            status=drf_status.HTTP_409_CONFLICT,
        )

    new_row = GeographicUnit.objects.create(
        level=level,
        code=code,
        name=name,
        parent=parent,
        effective_from=effective_from,
        status=GeographicUnit.Status.ACTIVE,
    )
    emit_audit(
        action="geo_unit.created",
        entity_type="reference_data.geographic_unit",
        entity_id=new_row.id,
        actor=request.user.username,
        reason=f"level={level} code={code}",
    )
    return Response(_geo_row(new_row), status=drf_status.HTTP_201_CREATED)


def _resolve_active(level: str, code: str) -> GeographicUnit:
    try:
        return GeographicUnit.objects.get(
            level=level, code=code, status=GeographicUnit.Status.ACTIVE,
        )
    except GeographicUnit.DoesNotExist as e:
        raise Http404(f"{level}:{code}") from e


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminConsoleUser])
def geography_detail(request, level: str, code: str):
    unit = _resolve_active(level, code)

    if request.method == "GET":
        # get_ancestors() orders by (level, code) alphabetically, which
        # doesn't match the topological hierarchy. Re-sort by the
        # canonical _LEVEL_ORDER so the chain reads region → village.
        level_index = {lvl: i for i, lvl in enumerate(_LEVEL_ORDER)}
        ancestors = sorted(
            unit.get_ancestors(),
            key=lambda a: level_index.get(a.level, 999),
        )
        descendants_count = unit.get_descendants().count()
        return Response({
            **_geo_row(unit),
            "ancestors": [_geo_row(a) for a in ancestors],
            "descendants_count": descendants_count,
        })

    # PATCH — versioned replacement
    body = request.data or {}
    new_name = body.get("name")
    new_parent_code = body.get("parent_code", ...)

    parent_arg: object = ...
    if new_parent_code is not ...:
        if new_parent_code in (None, ""):
            parent_arg = None
        else:
            parent_arg = GeographicUnit.objects.filter(
                code=new_parent_code, status=GeographicUnit.Status.ACTIVE,
            ).first()
            if parent_arg is None:
                return Response(
                    {"detail": f"parent_code {new_parent_code!r} not found or inactive"},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

    try:
        from apps.reference_data.lifecycle import (
            GeographicUnitReplaceError,
            replace_geographic_unit,
        )
        new_row = replace_geographic_unit(
            unit,
            actor=request.user.username,
            name=new_name,
            parent=parent_arg,
        )
    except GeographicUnitReplaceError as e:
        return Response({"detail": str(e)}, status=drf_status.HTTP_409_CONFLICT)
    return Response(_geo_row(new_row))


@api_view(["GET"])
@permission_classes([IsAdminConsoleUser])
def geography_history(request, level: str, code: str):
    """Full version history for a (level, code) — including inactive rows."""
    rows = (
        GeographicUnit.objects
        .filter(level=level, code=code)
        .order_by("-effective_from")
    )
    return Response({
        "level": level,
        "code": code,
        "history": [_geo_row(u) for u in rows],
    })


@api_view(["POST"])
@permission_classes([IsAdminConsoleUser])
def geography_import_ubos(request):
    """Bulk import from a UBOS feed. Gated to nsr_dba within the admin
    set — other admin groups get 403."""
    if not request.user.groups.filter(name="nsr_dba").exists() and not request.user.is_superuser:
        return Response(
            {"detail": "UBOS import is restricted to nsr_dba"},
            status=drf_status.HTTP_403_FORBIDDEN,
        )
    # Stub for now — the actual feed integration ships in a follow-up
    # ticket. We emit an audit event and return a 202 so the screen
    # has something to render against.
    emit_audit(
        action="geo_unit.ubos_import_started",
        entity_type="reference_data.geographic_unit",
        entity_id="*",
        actor=request.user.username,
        reason="UBOS bulk feed import",
    )
    return Response(
        {"detail": "UBOS import enqueued", "status": "accepted"},
        status=drf_status.HTTP_202_ACCEPTED,
    )
