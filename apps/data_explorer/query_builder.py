"""AggregateQueryService — composes ORM QuerySet ops against the
matview-backed unmanaged models, runs the suppressor, writes the
AggregateQueryLog row, and emits the metadata block.

Per ADR-0023:
- No raw SQL. Every aggregate is a Django ORM `values(...).annotate(
  count=Count('*'))` against an unmanaged matview model.
- The suppressor is the only path to a user-visible response.
- Stale matview → HTTP 503; the dispatcher (api.py) maps the
  StaleMatviewError exception.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db.models import Count

from .suppressor import Suppressor


class StaleMatviewError(Exception):
    """Raised when the matview's refreshed_at is older than 2x its
    nominal cadence. Maps to HTTP 503 + audit.matview.stale."""

    def __init__(self, matview: str, refreshed_at, staleness_seconds: int,
                 max_seconds: int):
        super().__init__(
            f"matview {matview} stale: refreshed_at={refreshed_at} "
            f"({staleness_seconds}s old, max {max_seconds}s)"
        )
        self.matview = matview
        self.refreshed_at = refreshed_at
        self.staleness_seconds = staleness_seconds
        self.max_seconds = max_seconds


@dataclass
class AggregateResult:
    rows: list[dict]
    suppressed_cell_count: int
    total_cell_count: int
    k_floor: int
    matview: str
    refreshed_at: datetime | None
    staleness_seconds: int
    strictest_class: str
    query_hash: str
    filter_hash: str


def _hash(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _apply_geographic_scope(qs, scope: dict):
    if not scope:
        return qs
    level = (scope.get("level") or "").lower()
    level = {
        "country": "national",
        "subregion": "sub_region",
        "sub-county": "sub_county",
        "subcounty": "sub_county",
    }.get(level, level)
    codes = list(scope.get("codes") or [])
    if not (level and codes):
        return qs
    field_map = {
        "sub_region": "sub_region_code",
        "district": "district_code",
        "sub_county": "sub_county_code",
    }
    column = field_map.get(level)
    if column is None:
        # Level was validated upstream — anything we don't have a
        # column for is a coarser-than-floor pass-through.
        return qs
    if not hasattr(qs.model, column):
        return qs
    return qs.filter(**{f"{column}__in": codes})


def _apply_filters(qs, filter_vars, filters):
    by_code = {v.code: v for v in filter_vars}
    if isinstance(filters, list):
        normalised = {}
        for f in filters:
            if not isinstance(f, dict):
                continue
            code = f.get("variable") or f.get("code")
            if code is None:
                continue
            op = (f.get("op") or "").lower() or None
            if "values" in f:
                normalised[code] = {"op": op or "in", "value": f["values"]}
            elif "value" in f:
                normalised[code] = {"op": op or "eq", "value": f["value"]}
        filters = normalised
    for code, value in (filters or {}).items():
        var = by_code.get(code)
        if var is None:
            continue
        column = var.source_field
        if not column or not hasattr(qs.model, column):
            continue
        if isinstance(value, dict):
            op = (value.get("op") or "eq").lower()
            raw_value = value.get("value")
        else:
            op = "in" if isinstance(value, list) else "eq"
            raw_value = value

        if raw_value == "" or raw_value == []:
            continue

        if op == "in":
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            qs = qs.filter(**{f"{column}__in": values})
        elif op == "neq":
            if isinstance(raw_value, list):
                qs = qs.exclude(**{f"{column}__in": raw_value})
            else:
                qs = qs.exclude(**{column: raw_value})
        elif op in {"gt", "gte", "lt", "lte"}:
            qs = qs.filter(**{f"{column}__{op}": raw_value})
        elif op == "between":
            values = raw_value
            if isinstance(values, str):
                values = [v.strip() for v in values.split(",") if v.strip()]
            if isinstance(values, (list, tuple)) and len(values) >= 2:
                qs = qs.filter(**{f"{column}__gte": values[0], f"{column}__lte": values[1]})
        else:
            qs = qs.filter(**{column: raw_value})
    return qs


def _matview_freshness(matview_model, cadence_seconds: int) -> tuple[datetime | None, int]:
    """Return (refreshed_at, staleness_seconds). Tolerates an empty
    matview — first row's refreshed_at is the freshness signal."""
    row = matview_model.objects.order_by("-refreshed_at").values("refreshed_at").first()
    if not row or not row.get("refreshed_at"):
        return None, 0
    refreshed_at = row["refreshed_at"]
    now = datetime.now(UTC)
    delta = max(int((now - refreshed_at).total_seconds()), 0)
    return refreshed_at, delta


def _build_groupby(projection_vars):
    """List of column names to group by — drops projection variables
    that don't have a backing matview column."""
    cols = []
    for v in projection_vars:
        col = v.source_field
        if not col:
            continue
        cols.append(col)
    return cols


class AggregateQueryService:

    @classmethod
    def execute(cls, *, validated_query, dataset_count_field: str = "household_count"):
        """Run the aggregate. `validated_query` is the ValidatedQuery
        returned by validators.validate(). Returns AggregateResult.

        The query is always a `values(group_by).annotate(count=Count('*'))`
        against the matview, with the dataset's count column folded
        into the aggregation (Sum over the precomputed counts).
        """
        from . import services

        dataset = validated_query.dataset
        matview_model = validated_query.matview_model
        cadence_seconds = dataset.refresh_cadence.interval_seconds
        # Stale matview fallback — 2x cadence. Staleness flows through
        # the services seam so the 503 branch is forceable in tests
        # without a populated matview; the freshness query for the
        # not-stale path runs only once we know we'll serve the result.
        staleness_seconds = services.compute_staleness_seconds(
            matview_model, cadence_seconds,
        )
        if cadence_seconds and staleness_seconds > 2 * cadence_seconds:
            raise StaleMatviewError(
                matview=dataset.source_matview,
                refreshed_at=None,
                staleness_seconds=staleness_seconds,
                max_seconds=2 * cadence_seconds,
            )
        refreshed_at, _ = _matview_freshness(matview_model, cadence_seconds)

        qs = matview_model.objects.all()
        qs = _apply_geographic_scope(qs, validated_query.geographic_scope)
        qs = _apply_filters(qs, validated_query.filter_variables,
                            getattr(validated_query, "filter_payload", {}))

        group_by = _build_groupby(validated_query.projection_variables)

        # Detect which precomputed count column the matview carries.
        candidate_counts = [
            "household_count", "member_count", "referral_count",
            "grievance_count",
        ]
        count_column = next(
            (c for c in candidate_counts if hasattr(matview_model, c)),
            None,
        )

        if group_by:
            qs = qs.values(*group_by)
        else:
            qs = qs.values()

        if count_column:
            from django.db.models import Sum
            qs = qs.annotate(count=Sum(count_column))
        else:
            qs = qs.annotate(count=Count("*"))

        rows = [dict(r) for r in qs]
        # Materialise count as int (Sum returns None for empty groups).
        for r in rows:
            r["count"] = int(r.get("count") or 0)

        sup = Suppressor.apply(
            rows,
            strictest_class_code=validated_query.strictest_class.code,
            k_floor=validated_query.strictest_class.k_floor,
        )

        query_hash = _hash({
            "dataset": dataset.code,
            "projection": [v.code for v in validated_query.projection_variables],
            "filters": getattr(validated_query, "filter_payload", {}),
            "geographic_scope": validated_query.geographic_scope,
        })
        filter_hash = _hash({
            "filters": getattr(validated_query, "filter_payload", {}),
            "geographic_scope": validated_query.geographic_scope,
        })

        return AggregateResult(
            rows=sup.rows,
            suppressed_cell_count=sup.suppressed_cell_count,
            total_cell_count=sup.total_cell_count,
            k_floor=sup.k_floor,
            matview=dataset.source_matview,
            refreshed_at=refreshed_at,
            staleness_seconds=staleness_seconds,
            strictest_class=sup.strictest_class,
            query_hash=query_hash,
            filter_hash=filter_hash,
        )


def write_query_log(*, actor: str, dataset, validated_query,
                    result: AggregateResult) -> None:
    """Persist the AggregateQueryLog row for the executed aggregate.
    The detect_overlap_burst Celery task reads these to flag re-
    identification bursts."""
    from .models import AggregateQueryLog
    AggregateQueryLog.objects.create(
        actor=actor,
        dataset=dataset,
        projection_variables=[v.code for v in validated_query.projection_variables],
        filter_variables=[v.code for v in validated_query.filter_variables],
        filter_hash=result.filter_hash,
        geographic_scope=validated_query.geographic_scope or {},
        result_row_count=result.total_cell_count,
        suppressed_cell_count=result.suppressed_cell_count,
        strictest_privacy_class=result.strictest_class,
        query_hash=result.query_hash,
        matview_refreshed_at=result.refreshed_at,
        staleness_seconds=result.staleness_seconds,
    )
