"""Seed the four Sprint 0 DIH connectors per SAD §11.1 (MVP Release 1):

  UBOS bulk          (kind=ubos)         — one-off historic load
  CAPI walk-in       (kind=capi_walkin)
  Web on-demand      (kind=web)
  Kobo               (kind=kobo)         — pilot and testing

Each gets a SourceSystem + an active DataProvisionAgreement so connector
runs can start (AC-DIH-DPA-REQUIRED).

Idempotent: re-runs leave existing rows alone.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsr_mis.settings")
django.setup()

from apps.ingestion_hub.models import (  # noqa: E402
    Connector, DataProvisionAgreement, SourceSystem, SourceSystemKind,
)


SOURCES = [
    {"code": "UBOS-BULK", "name": "UBOS mass enumeration", "kind": SourceSystemKind.UBOS,
     "connector": "ubos-historic-load", "residence_days": 90},
    {"code": "CAPI-WALKIN", "name": "CAPI walk-in submissions", "kind": SourceSystemKind.CAPI_WALKIN,
     "connector": "capi-default", "residence_days": 30},
    {"code": "WEB-OD", "name": "Web on-demand intake", "kind": SourceSystemKind.WEB,
     "connector": "web-default", "residence_days": 30},
    {"code": "KOBO-PILOT", "name": "Kobo pilot", "kind": SourceSystemKind.KOBO,
     "connector": "kobo-pilot", "residence_days": 30},
]


def seed() -> int:
    created = 0
    for spec in SOURCES:
        src, src_new = SourceSystem.objects.get_or_create(
            code=spec["code"],
            defaults={"name": spec["name"], "kind": spec["kind"]},
        )
        dpa, dpa_new = DataProvisionAgreement.objects.get_or_create(
            source_system=src,
            reference=f"DPA-{spec['code']}-2026",
            defaults={
                "valid_from": date(2026, 1, 1),
                "valid_to": date(2031, 12, 31),
                "residence_policy_days": spec["residence_days"],
                "purpose": "Sprint 0 baseline DPA — replace before partner onboarding (DRS-O-01).",
            },
        )
        conn, conn_new = Connector.objects.get_or_create(
            source_system=src, name=spec["connector"],
        )
        if src_new or dpa_new or conn_new:
            created += 1
            print(f"  {spec['code']}: source={src_new} dpa={dpa_new} connector={conn_new}")
        else:
            print(f"  {spec['code']}: already configured")
    return created


if __name__ == "__main__":
    n = seed()
    print(f"\nseeded {n} new source(s); total: {SourceSystem.objects.count()}")
