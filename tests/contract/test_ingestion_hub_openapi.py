"""Contract tests for `/docs/openapi/ingestion_hub.yaml` (US-S11-003c).

We're not exercising live HTTP yet — the credential admin is a Django
admin surface today (see ADR-0007). What we DO test:

1. The spec parses as valid YAML.
2. The OpenAPI version is 3.x.
3. The ConnectionTestResult schema matches the Python dataclass the
   KoboConnector returns (drift here means the spec lies).
4. The ConnectorRunType enum matches the model's TextChoices.
5. The SourceSystemKind enum matches the model's TextChoices.

Failures here ALWAYS mean the spec drifted away from the code; the
code is the source of truth in NSR.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml
from apps.ingestion_hub.connectors.base import ConnectionTestResult
from apps.ingestion_hub.models import (
    ConnectorRunType,
    SourceSystemKind,
)

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi" / "ingestion_hub.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text())


def test_spec_parses(spec):
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"]


def test_connection_test_result_schema_matches_dataclass(spec):
    schema = spec["components"]["schemas"]["ConnectionTestResult"]
    field_names = {f.name for f in dataclasses.fields(ConnectionTestResult)}
    schema_props = set(schema["properties"].keys())
    assert field_names == schema_props, (
        f"ConnectionTestResult drift: dataclass={field_names}, spec={schema_props}"
    )
    # Required-set check: ok + latency_ms are non-default fields.
    required_in_spec = set(schema["required"])
    required_in_code = {
        f.name
        for f in dataclasses.fields(ConnectionTestResult)
        if f.default is dataclasses.MISSING
    }
    assert required_in_code <= required_in_spec, (
        f"Required-field drift: code requires {required_in_code}, "
        f"spec requires {required_in_spec}"
    )


def test_connector_run_type_enum_matches_model(spec):
    enum_in_spec = set(spec["components"]["schemas"]["ConnectorRunType"]["enum"])
    enum_in_code = {v.value for v in ConnectorRunType}
    assert enum_in_spec == enum_in_code


def test_source_system_kind_enum_matches_model(spec):
    enum_in_spec = set(spec["components"]["schemas"]["SourceSystemKind"]["enum"])
    enum_in_code = {v.value for v in SourceSystemKind}
    assert enum_in_spec == enum_in_code


def test_trigger_run_path_documented(spec):
    """US-S11-021 — the console "Run connector" button posts to this
    path. The spec lives under `paths_appended_2026_05_25` (a
    flat-list extension to the original Sprint 11 surface)."""
    appended = spec["paths_appended_2026_05_25"]
    path = "/api/v1/dih/source-systems/{id}/trigger-run/"
    assert path in appended, sorted(appended.keys())
    op = appended[path]["post"]
    assert "dih" in op["tags"]
    # Response shape covers the operator-visible counts the UI displays.
    body = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert {"run_id", "dry_run", "landed", "staged", "note"} <= set(body["properties"])
    # 4xx documented for IsDihTrigger denial + precondition failures.
    assert "400" in op["responses"]
    assert "403" in op["responses"]


def test_nira_vital_events_webhook_documented(spec):
    """US-114 restore — the NIRA reverse feed is push-based; its inbound
    endpoint must be in the spec with the signature header and the
    four recorded outcomes the view returns."""
    appended = spec["paths_appended_2026_09_10"]
    path = "/api/v1/dih/nira/vital-events/"
    assert path in appended, sorted(appended.keys())
    op = appended[path]["post"]
    header_names = {p["name"] for p in op.get("parameters", [])}
    assert "X-NIRA-Signature" in header_names
    body = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert set(body["properties"]["outcome"]["enum"]) == {
        "committed", "noop", "quarantined", "duplicate",
    }
    for code in ("400", "401", "503"):
        assert code in op["responses"]


def test_supported_kinds_are_in_the_kind_enum(spec):
    from apps.ingestion_hub.connection_test import PULL_KINDS, SUPPORTED_KINDS
    enum_in_spec = set(spec["components"]["schemas"]["SourceSystemKind"]["enum"])
    assert {k.value for k in SUPPORTED_KINDS} <= enum_in_spec
    assert PULL_KINDS <= SUPPORTED_KINDS
