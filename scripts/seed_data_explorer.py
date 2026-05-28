"""DATA-EXP seed bootstrap — idempotent.

Usage:
    python manage.py shell -c "exec(open('scripts/seed_data_explorer.py').read())"

Seeds:
  - 4 PrivacyClass rows (Public, Internal, Personal, Sensitive)
  - 5 RefreshCadence rows (manual, hourly, daily, weekly, monthly)
  - Initial Dataset rows from DATASET_DEFAULTS
  - Variable rows from metadata_loader.refresh() — seeded INACTIVE so the
    dual-approval workflow has work to do.

If the Data Analyst has already produced
/scripts/data_explorer/catalogue_seed.yaml, this script reads it and
upserts (privacy-class + dataset overrides). Otherwise it falls back
to the model-introspection path baked into the loader.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import django  # noqa: F401 — required when run via `manage.py shell -c`

# Allow running via `python scripts/seed_data_explorer.py` after a
# DJANGO_SETTINGS_MODULE env-var bootstrap (the manage.py shell route
# already has Django configured).
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ["DJANGO_SETTINGS_MODULE"] = "nsr_mis.settings"
    django.setup()


# --- Imports ---------------------------------------------------------------

from apps.data_explorer import catalogue, metadata_loader  # noqa: E402
from apps.data_explorer.models import (  # noqa: E402
    Dataset,
    PrivacyClass,
    RefreshCadence,
)
from apps.data_explorer.seeds.privacy_class_defaults import (  # noqa: E402
    DATASET_DEFAULTS,
    PRIVACY_CLASS_DEFAULTS,
    REFRESH_CADENCE_DEFAULTS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE_SEED_YAML = REPO_ROOT / "scripts" / "data_explorer" / "catalogue_seed.yaml"


def _seed_privacy_classes() -> int:
    created = 0
    for row in PRIVACY_CLASS_DEFAULTS:
        _, was_created = PrivacyClass.objects.update_or_create(
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
        if was_created:
            created += 1
    return created


def _seed_refresh_cadences() -> int:
    created = 0
    for row in REFRESH_CADENCE_DEFAULTS:
        _, was_created = RefreshCadence.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "interval_seconds": row["interval_seconds"],
            },
        )
        if was_created:
            created += 1
    return created


def _seed_datasets() -> int:
    created = 0
    for row in DATASET_DEFAULTS:
        pc = PrivacyClass.objects.get(code=row["privacy_class"])
        rc = RefreshCadence.objects.get(code=row["refresh"])
        _, was_created = Dataset.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "source_matview": row["matview"],
                "privacy_class": pc,
                "refresh_cadence": rc,
                "geographic_floor": row["geographic_floor"],
            },
        )
        if was_created:
            created += 1
    return created


def _apply_yaml_overrides(path: Path) -> dict:
    """When the Data Analyst's catalogue_seed.yaml exists, upsert
    dataset + privacy-class overrides from it. Schema is loose by
    design — keys we don't recognise are ignored."""
    try:
        import yaml
    except ImportError:
        sys.stderr.write(
            "PyYAML not installed; skipping catalogue_seed.yaml overrides.\n"
        )
        return {"applied": False, "reason": "yaml-not-installed"}

    if not path.exists():
        return {"applied": False, "reason": "no-yaml"}

    with path.open() as f:
        data = yaml.safe_load(f) or {}

    counts = {"datasets": 0, "privacy_classes": 0}
    for row in data.get("privacy_classes") or []:
        PrivacyClass.objects.update_or_create(
            code=row["code"],
            defaults={k: v for k, v in row.items() if k != "code"},
        )
        counts["privacy_classes"] += 1
    for row in data.get("datasets") or []:
        code = row.pop("code")
        pc_code = row.pop("privacy_class", None)
        rc_code = row.pop("refresh", None)
        defaults = dict(row)
        if pc_code:
            defaults["privacy_class"] = PrivacyClass.objects.get(code=pc_code)
        if rc_code:
            defaults["refresh_cadence"] = RefreshCadence.objects.get(code=rc_code)
        Dataset.objects.update_or_create(code=code, defaults=defaults)
        counts["datasets"] += 1

    return {"applied": True, "counts": counts}


def run():
    print("[seed_data_explorer] starting…")
    pc = _seed_privacy_classes()
    rc = _seed_refresh_cadences()
    ds = _seed_datasets()
    yaml_result = _apply_yaml_overrides(CATALOGUE_SEED_YAML)
    print(f"  privacy_classes: +{pc} new")
    print(f"  refresh_cadences: +{rc} new")
    print(f"  datasets: +{ds} new")
    print(f"  yaml_overrides: {yaml_result}")
    print("[seed_data_explorer] running metadata_loader.refresh()…")
    refresh_result = metadata_loader.refresh()
    print(f"  variables: {refresh_result}")
    catalogue.invalidate()
    print("[seed_data_explorer] done.")


# When executed via `exec(open(...).read())` __name__ is "__main__"; when
# imported it stays as the module name. Run on either.
run()
