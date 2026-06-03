"""Metadata loader — single source of truth for the DATA-EXP catalogue.

ADR-0023 D5: catalogue rows are *not* hand-curated. The loader upserts
Dataset + Variable rows by (dataset_code, variable_code) from the
live matview-backed explorer seed in
apps.data_explorer.seeds.privacy_class_defaults.

Loader lifecycle:
- refresh() is idempotent. Newly-added variables seed INACTIVE.
- Variables whose underlying field SHAPE changes (data_type, choice
  list, source_field) flip to INACTIVE and bump `version` so dual
  approval is required to re-activate.
- refresh(activate=True) is the explicit bootstrap path that marks the
  live explorer catalogue ACTIVE in development / seeded environments.
- Called on Django startup (apps.py) AND on the post_migrate signal
  (signals.py) so the catalogue tracks model migrations.

The loader writes to `default` (the catalogue is metadata, not data).
"""

from __future__ import annotations

import hashlib
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def _shape_hash(*, data_type: str, source_model: str, source_field: str,
                choice_list: str, choice_kind: str) -> str:
    payload = "|".join([
        data_type or "", source_model or "", source_field or "",
        choice_list or "", choice_kind or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_seed_rows():
    """Upsert PrivacyClass + RefreshCadence defaults. Called by refresh()
    so a fresh DB doesn't crash on FK validation."""
    from .models import PrivacyClass, RefreshCadence
    from .seeds.privacy_class_defaults import (
        PRIVACY_CLASS_DEFAULTS,
        REFRESH_CADENCE_DEFAULTS,
    )

    for row in PRIVACY_CLASS_DEFAULTS:
        PrivacyClass.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "description": row["description"],
                "k_floor": row["k_floor"],
                "daily_user_cap": row["daily_user_cap"],
                "daily_org_cap": row["daily_org_cap"],
                "blocks_aggregate": row["blocks_aggregate"],
            },
        )
    for row in REFRESH_CADENCE_DEFAULTS:
        RefreshCadence.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "interval_seconds": row["interval_seconds"],
            },
        )


def _ensure_datasets():
    """Upsert the default Dataset rows. Datasets are stable across
    schema migrations — only their underlying matviews change."""
    from .models import Dataset, PrivacyClass, RefreshCadence
    from .seeds.privacy_class_defaults import DATASET_DEFAULTS

    out = {}
    for row in DATASET_DEFAULTS:
        pc = PrivacyClass.objects.get(code=row["privacy_class"])
        rc = RefreshCadence.objects.get(code=row["refresh"])
        ds, _ = Dataset.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "source_matview": row["matview"],
                "privacy_class": pc,
                "refresh_cadence": rc,
                "geographic_floor": row["geographic_floor"],
            },
        )
        out[row["code"]] = ds
    return out


def _upsert_variable(*, dataset, code, label, data_type, source_model,
                     source_field, choice_list, choice_kind,
                     privacy_class, questionnaire_section):
    """Insert / refresh one Variable row.

    Shape-change rule: if the recomputed shape_hash differs from the
    stored value, flip status back to INACTIVE and bump version so the
    dual-approval workflow has work to do.
    """
    from .models import Variable, VariableStatus

    sh = _shape_hash(
        data_type=data_type,
        source_model=source_model,
        source_field=source_field,
        choice_list=choice_list,
        choice_kind=choice_kind,
    )
    existing = Variable.objects.filter(dataset=dataset, code=code).first()
    if existing is None:
        Variable.objects.create(
            dataset=dataset,
            code=code,
            label=label,
            data_type=data_type,
            source_model=source_model,
            source_field=source_field,
            choice_list=choice_list,
            choice_kind=choice_kind,
            privacy_class=privacy_class,
            status=VariableStatus.INACTIVE,
            questionnaire_section=questionnaire_section,
            shape_hash=sh,
            version=1,
        )
        return "created"
    if existing.shape_hash != sh:
        existing.label = label
        existing.data_type = data_type
        existing.source_model = source_model
        existing.source_field = source_field
        existing.choice_list = choice_list
        existing.choice_kind = choice_kind
        existing.questionnaire_section = questionnaire_section
        existing.shape_hash = sh
        existing.version += 1
        existing.status = VariableStatus.INACTIVE
        existing.save()
        return "shape_changed"
    # Stable: keep ACTIVE status if it's already there; label/section
    # are cheap to refresh without forcing re-approval.
    dirty = False
    if existing.label != label:
        existing.label = label
        dirty = True
    if existing.questionnaire_section != questionnaire_section:
        existing.questionnaire_section = questionnaire_section
        dirty = True
    if dirty:
        existing.save(update_fields=["label", "questionnaire_section",
                                     "updated_at"])
    return "stable"


def _retire_stale_variables(*, dataset, keep_codes: set[str]) -> int:
    from .models import Variable, VariableStatus

    stale = list(
        Variable.objects
        .filter(dataset=dataset)
        .exclude(code__in=keep_codes)
    )
    if not stale:
        return 0
    for v in stale:
        if v.status != VariableStatus.DEPRECATED:
            v.status = VariableStatus.DEPRECATED
            v.save(update_fields=["status", "updated_at"])
    return len(stale)


def _activate_loaded_variables(*, dataset, keep_codes: set[str],
                               actor_prefix: str = "system-metadata-loader") -> int:
    from .models import ApprovalRole, Variable, VariableApproval, VariableStatus

    variables = list(
        Variable.objects.filter(dataset=dataset, code__in=keep_codes)
    )
    if not variables:
        return 0

    activated = 0
    for v in variables:
        VariableApproval.objects.update_or_create(
            variable=v,
            approval_role=ApprovalRole.DQA,
            defaults={
                "approver": f"{actor_prefix}-dqa",
                "note": "bootstrap live aggregate metadata",
            },
        )
        VariableApproval.objects.update_or_create(
            variable=v,
            approval_role=ApprovalRole.DPO,
            defaults={
                "approver": f"{actor_prefix}-dpo",
                "note": "bootstrap live aggregate metadata",
            },
        )
        if v.status != VariableStatus.ACTIVE:
            v.status = VariableStatus.ACTIVE
            v.save(update_fields=["status", "updated_at"])
            activated += 1
    return activated


def _tables_ready() -> bool:
    """Best-effort check: are the catalogue tables present? Tolerates
    the pre-migrate case (apps.py startup, fresh-DB test runs)."""
    from django.db import connection
    expected = "data_explorer_dataset"
    try:
        return expected in connection.introspection.table_names()
    except Exception:  # noqa: BLE001
        return False


def refresh(*, quiet: bool = False, activate: bool = False) -> dict:
    """Idempotently refresh PrivacyClass + RefreshCadence + Dataset +
    Variable rows from the live explorer seed. Returns a tally dict.

    quiet=True suppresses the "no tables" warning at app-ready time
    (the post_migrate signal will run this again after migrations).
    """
    if not _tables_ready():
        if not quiet:
            logger.warning(
                "data_explorer.metadata_loader: tables not present yet "
                "(skipping refresh). Run migrate to land 0001_initial.",
            )
        return {
            "created": 0,
            "shape_changed": 0,
            "stable": 0,
            "deprecated": 0,
            "activated": 0,
            "skipped": True,
        }

    # Import inside refresh so signal handlers + AppConfig.ready aren't
    # paying the catalog cost unless the loader actually runs.
    from .seeds.privacy_class_defaults import DATASET_VARIABLE_DEFAULTS

    with transaction.atomic():
        _ensure_seed_rows()
        datasets_by_code = _ensure_datasets()

        tally = {
            "created": 0,
            "shape_changed": 0,
            "stable": 0,
            "deprecated": 0,
            "activated": 0,
            "skipped": False,
        }

        for dataset_code, variable_rows in DATASET_VARIABLE_DEFAULTS.items():
            ds = datasets_by_code.get(dataset_code)
            if ds is None:
                continue
            keep_codes: set[str] = set()
            for f in variable_rows:
                keep_codes.add(f["code"])
                outcome = _upsert_variable(
                    dataset=ds,
                    code=f["code"],
                    label=f["label"],
                    data_type=f["data_type"],
                    source_model=ds.source_matview,
                    source_field=f["source_field"],
                    choice_list="",
                    choice_kind="",
                    privacy_class=ds.privacy_class,
                    questionnaire_section="",
                )
                tally[outcome] += 1
            tally["deprecated"] += _retire_stale_variables(
                dataset=ds,
                keep_codes=keep_codes,
            )
            if activate:
                tally["activated"] += _activate_loaded_variables(
                    dataset=ds,
                    keep_codes=keep_codes,
                )

    return tally
