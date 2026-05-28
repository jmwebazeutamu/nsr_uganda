"""QueryValidator — runs the pre-execution checks for the aggregate
endpoint. ADR-0023 D3 + D4.

Checks (in order):
1. Dataset exists and is bound to a matview.
2. Every projected and filtered variable exists, belongs to the
   dataset, and is ACTIVE.
3. Strictest privacy class across all variables.
4. Strictest class is not Sensitive (refuse at 422).
5. Geographic scope is at or above the dataset's geographic_floor.

Returns a dict with the validated query, the strictest class, and the
matview model the query_builder will run against. Raises
ValidationError with a stable error code that the API serialiser maps
to a 422 + the right machine-readable payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from .matview_models import MATVIEW_MODELS
from .models import PrivacyClass, Variable, VariableStatus

# Stable error codes — match the OpenAPI 422 schemas verbatim.
ERR_DATASET_NOT_FOUND       = "dataset_not_found"
ERR_DATASET_NOT_BOUND       = "dataset_not_bound"
ERR_VARIABLE_NOT_FOUND      = "variable_not_found"
ERR_VARIABLE_INACTIVE       = "variable_inactive"
ERR_VARIABLE_WRONG_DATASET  = "variable_wrong_dataset"
ERR_SENSITIVE_BLOCKED       = "sensitive_class_blocked"
ERR_GEOGRAPHIC_FLOOR        = "geographic_floor_violation"
ERR_BAD_PAYLOAD             = "bad_payload"


# Geographic level rank — coarser → smaller integer. Used to compare
# the requested level against the dataset's floor.
_GEO_LEVELS = {
    "national": 0,
    "region": 1,
    "sub_region": 2,
    "district": 3,
    "county": 4,
    "sub_county": 5,
    "parish": 6,
    "village": 7,
}


@dataclass
class ValidatedQuery:
    dataset: object
    matview_model: type
    projection_variables: list[Variable]
    filter_variables: list[Variable]
    geographic_scope: dict
    strictest_class: PrivacyClass


class ValidationError(Exception):
    def __init__(self, code: str, *, detail: str = "", extras: dict | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.extras = extras or {}


def _strictest(classes: list[PrivacyClass]) -> PrivacyClass:
    """Return the strictest privacy class in the list. Sensitive >
    Personal > Internal > Public, ordered by k_floor + blocks_aggregate
    flag.

    Note: Public has k_floor=0 but is the loosest; Sensitive also has
    k_floor=0 (no aggregates allowed) but is the strictest. We rank
    by code priority then k_floor so the order is stable.
    """
    rank = {"public": 0, "internal": 1, "personal": 2, "sensitive": 3}
    return max(classes, key=lambda c: (rank.get(c.code, 0), c.k_floor))


def validate(payload: dict) -> ValidatedQuery:
    if not isinstance(payload, dict):
        raise ValidationError(ERR_BAD_PAYLOAD, detail="payload must be an object")
    # Accept either `dataset` (Coder spec) or `dataset_code` (Tester /
    # OpenAPI spec). Same value either way.
    dataset_code = payload.get("dataset") or payload.get("dataset_code")
    if not dataset_code:
        raise ValidationError(ERR_BAD_PAYLOAD, detail="dataset is required")

    from .models import Dataset

    dataset = (
        Dataset.objects
        .select_related("privacy_class", "refresh_cadence")
        .filter(code=dataset_code)
        .first()
    )
    if dataset is None:
        raise ValidationError(ERR_DATASET_NOT_FOUND,
                              detail=f"unknown dataset {dataset_code!r}")
    if not dataset.source_matview:
        raise ValidationError(ERR_DATASET_NOT_BOUND,
                              detail=f"dataset {dataset_code!r} has no matview")

    matview_model = MATVIEW_MODELS.get(dataset.source_matview)
    if matview_model is None:
        raise ValidationError(
            ERR_DATASET_NOT_BOUND,
            detail=f"matview {dataset.source_matview!r} unknown to the runtime",
        )

    projection_codes = list(payload.get("projection") or [])
    filter_codes = list((payload.get("filters") or {}).keys())

    all_codes = set(projection_codes) | set(filter_codes)
    if not all_codes:
        # An empty query against the dataset is permitted — it counts
        # rows at the dataset's natural grain. Skip Variable lookup.
        projection_vars = []
        filter_vars = []
    else:
        rows = list(Variable.objects.filter(
            dataset=dataset, code__in=all_codes,
        ).select_related("privacy_class"))
        by_code = {v.code: v for v in rows}

        missing = all_codes - set(by_code)
        if missing:
            raise ValidationError(
                ERR_VARIABLE_NOT_FOUND,
                detail=f"unknown variables: {sorted(missing)}",
                extras={"missing": sorted(missing)},
            )
        inactive = [v.code for v in rows if v.status != VariableStatus.ACTIVE]
        if inactive:
            raise ValidationError(
                ERR_VARIABLE_INACTIVE,
                detail=f"inactive variables: {sorted(inactive)}",
                extras={"inactive": sorted(inactive)},
            )

        projection_vars = [by_code[c] for c in projection_codes]
        filter_vars = [by_code[c] for c in filter_codes]

    relevant_vars = projection_vars + filter_vars
    classes = [v.privacy_class for v in relevant_vars] + [dataset.privacy_class]
    strict = _strictest(classes)

    if strict.blocks_aggregate or strict.code == "sensitive":
        raise ValidationError(
            ERR_SENSITIVE_BLOCKED,
            detail="sensitive variables cannot be aggregated",
            extras={
                "handoff": "/api/v1/data-requests/draft",
            },
        )

    geographic_scope = payload.get("geographic_scope") or {}
    level = (geographic_scope.get("level") or "").lower()
    if level:
        if level not in _GEO_LEVELS:
            raise ValidationError(
                ERR_BAD_PAYLOAD,
                detail=f"unknown geographic level {level!r}",
            )
        floor = dataset.geographic_floor or "sub_county"
        if _GEO_LEVELS[level] > _GEO_LEVELS.get(floor, _GEO_LEVELS["sub_county"]):
            raise ValidationError(
                ERR_GEOGRAPHIC_FLOOR,
                detail=(
                    f"aggregate not available below {floor}; "
                    f"use the record-level handoff for {level} data"
                ),
                extras={
                    "floor": floor,
                    "requested": level,
                    "handoff": "/api/v1/data-requests/draft",
                },
            )

    return ValidatedQuery(
        dataset=dataset,
        matview_model=matview_model,
        projection_variables=projection_vars,
        filter_variables=filter_vars,
        geographic_scope=geographic_scope,
        strictest_class=strict,
    )


class QueryValidator:
    """Class-shaped wrapper around the `validate(payload)` function.
    Exists so callers (and tests) can write `QueryValidator.validate(...)`
    in the Coder's original module style. The function form is the
    canonical implementation."""

    @staticmethod
    def validate(payload: dict) -> ValidatedQuery:
        return validate(payload)
