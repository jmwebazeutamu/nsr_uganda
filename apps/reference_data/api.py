import hashlib
import json
from datetime import date, datetime

from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ChoiceList, ChoiceListStatus, ChoiceOption, GeographicUnit


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


# --- US-S22-005e — Bundle endpoint for CAPI / web intake ---------------------
#
# A single round-trip that returns every ACTIVE ChoiceList at `as_of`
# with its options for `lang`. Form runtimes (Android CAPI in US-081,
# web intake form) fetch this and render dropdowns directly off the
# response — no hardcoded option lists anywhere in app code (ADR-0010
# §6). An ETag (sha256 of the JSON bytes) lets clients short-circuit
# unchanged-payload responses to 304.

def _build_bundle(as_of: date, lang: str, names: list[str] | None = None) -> dict:
    """Compute the bundle deterministically — sorted by list_name —
    so the ETag is stable across calls when nothing has changed.

    `names` (US-S23-011) optionally restricts the bundle to a subset
    of list_names. The wizard fetches only the lists it needs
    (`partner_type`, `partner_sector`, etc.) instead of the whole
    60-list catalogue.
    """
    qs = (
        ChoiceList.objects
        .filter(status=ChoiceListStatus.ACTIVE)
        .filter(Q(effective_from__isnull=True) | Q(effective_from__lte=as_of))
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
    )
    if names is not None:
        qs = qs.filter(list_name__in=names)
    active_lists = (
        qs.prefetch_related("options")
        .order_by("list_name", "-version")
    )
    # Keep only the highest version per list_name (active overlap is
    # an open item — OI-S22-2 in ADR-0010).
    seen: set[str] = set()
    selected: list[ChoiceList] = []
    for cl in active_lists:
        if cl.list_name in seen:
            continue
        seen.add(cl.list_name)
        selected.append(cl)
    selected.sort(key=lambda c: c.list_name)

    lists = []
    for cl in selected:
        # Build options: primary language overlays, falling back to en.
        rows_by_code: dict[str, dict] = {}
        for opt in cl.options.all():
            if opt.status != ChoiceOption.Status.ACTIVE:
                continue
            # Always seed with en, then let lang override.
            existing = rows_by_code.get(opt.code, {})
            if opt.language == "en" and "en_label" not in existing:
                existing["en_label"] = opt.label
                existing["sort_order"] = opt.sort_order
                existing["parent_code"] = opt.parent_code
            if opt.language == lang and lang != "en":
                existing["lang_label"] = opt.label
            rows_by_code[opt.code] = existing
        options = []
        for code, row in rows_by_code.items():
            label = row.get("lang_label") or row.get("en_label") or code
            options.append({
                "code": code,
                "label": label,
                "sort_order": row.get("sort_order", 0),
                "parent_code": row.get("parent_code", ""),
            })
        options.sort(key=lambda o: (o["sort_order"], o["code"]))
        lists.append({
            "list_name": cl.list_name,
            "version": cl.version,
            "options": options,
        })

    return {
        "as_of": as_of.isoformat(),
        "lang": lang,
        "lists": lists,
    }


def _bundle_etag(bundle: dict) -> str:
    """Stable sha256 over a canonical JSON serialisation."""
    body = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    # Strong ETag per RFC 7232 §2.3 — quoted hex string.
    return f'"{digest}"'


@extend_schema(
    tags=["reference-data"],
    summary="Choice list bundle for questionnaire runtimes",
    description=(
        "Returns every ACTIVE ChoiceList at `as_of` with its options "
        "rendered in `lang` (falling back to en when a language row "
        "is missing). CAPI fetches this on every sync; the web intake "
        "form fetches on load. Send `If-None-Match` with a prior ETag "
        "to short-circuit unchanged-payload responses to 304."
    ),
    parameters=[
        OpenApiParameter(
            name="as_of",
            type=OpenApiTypes.DATE,
            required=False,
            description="Resolution date (defaults to today, EAT).",
        ),
        OpenApiParameter(
            name="lang",
            type=OpenApiTypes.STR,
            required=False,
            description="Language code (defaults to en).",
        ),
        OpenApiParameter(
            name="lists",
            type=OpenApiTypes.STR,
            required=False,
            description=(
                "Comma-separated list_name allowlist. When omitted the "
                "full catalogue is returned; when set only the named "
                "lists ship. Useful for the wizard's targeted fetches."
            ),
        ),
    ],
)
class ChoiceListBundleView(APIView):
    """ADR-0010 §6. Single-round-trip bundle for form runtimes."""

    def get(self, request):
        as_of_str = request.query_params.get("as_of")
        if as_of_str:
            try:
                as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "as_of must be YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            from django.utils import timezone
            as_of = timezone.localdate()
        lang = request.query_params.get("lang") or "en"
        names_param = (request.query_params.get("lists") or "").strip()
        names = (
            [n.strip() for n in names_param.split(",") if n.strip()]
            if names_param else None
        )

        bundle = _build_bundle(as_of, lang, names=names)
        etag = _bundle_etag(bundle)

        if_none_match = request.META.get("HTTP_IF_NONE_MATCH")
        if if_none_match and if_none_match.strip() == etag:
            resp = Response(status=status.HTTP_304_NOT_MODIFIED)
            resp["ETag"] = etag
            return resp

        resp = Response(bundle)
        resp["ETag"] = etag
        resp["Cache-Control"] = "private, max-age=60, must-revalidate"
        return resp
