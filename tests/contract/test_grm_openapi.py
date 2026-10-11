"""Contract tests for `/docs/openapi/grm.yaml`.

The spec is hand-written, so the only thing keeping it true is a test
that reads the code and compares. Failures here always mean the spec
drifted; the code is the source of truth.

What is checked is chosen for where drift would actually mislead a
client: the attachment-limits response shape (the console renders it
instead of keeping its own copy of the policy), the push outcome
vocabulary, and the idempotency-key pattern (STAAC builds that string
from its side, so a pattern that disagrees with our parser is a
contract nobody can satisfy).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SPEC = Path(__file__).resolve().parents[2] / "docs" / "openapi" / "grm.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC.read_text())


def test_it_parses_as_openapi_3(spec):
    assert spec["openapi"].startswith("3.")


def test_the_limits_schema_matches_the_serializer(spec):
    """The console renders these keys. A key the server stops sending
    is a blank line in the dialog; one it starts sending unannounced
    is undocumented contract."""
    from apps.grievance.api import _AttachmentLimits

    documented = set(
        spec["components"]["schemas"]["AttachmentLimits"]["properties"],
    )
    served = set(_AttachmentLimits().get_fields())
    assert documented == served


def test_the_limits_schema_carries_no_values(spec):
    """The numbers belong to `evidence_storage`. A copy in the spec
    would be a second policy, and specs are not run."""
    from apps.update_workflow.evidence_storage import (
        MAX_FILE_BYTES,
        MAX_TOTAL_BYTES,
    )

    text = SPEC.read_text()
    # The byte caps are distinctive enough to grep for. MAX_FILES is
    # 3, which also spells the OpenAPI version, so it is checked by
    # shape instead: no property may carry a value at all.
    for value in (MAX_FILE_BYTES, MAX_TOTAL_BYTES):
        assert str(value) not in text, (
            f"{value} is hardcoded in grm.yaml; document the shape, not "
            "the policy"
        )
    for name, prop in (
        spec["components"]["schemas"]["AttachmentLimits"]["properties"].items()
    ):
        stated = {"default", "example", "const", "enum"} & set(prop)
        assert not stated, (
            f"AttachmentLimits.{name} states {sorted(stated)}; the values "
            "belong to apps.update_workflow.evidence_storage"
        )


def test_the_push_outcomes_are_the_ones_the_code_can_return(spec):
    from apps.grievance.models import HandoverOutcome

    documented = set(
        spec["components"]["schemas"]["PushAccepted"]["properties"]
        ["outcome"]["enum"],
    )
    assert documented == set(HandoverOutcome.values)


def test_the_idempotency_pattern_accepts_what_the_parser_accepts(spec):
    """STAAC builds this string. A pattern our own parser rejects is a
    contract nobody can satisfy."""
    from apps.grievance.external.receiver import parse_idempotency_key

    path = spec["paths"]["/partners/staac/handovers/"]["post"]
    header = next(
        p for p in path["parameters"] if p["name"] == "Idempotency-Key"
    )
    pattern = re.compile(header["schema"]["pattern"])

    good = "partner:d8f05c04-4b0f-4e28-9d87-95c88e6c6a09:2:handover"
    assert pattern.match(good)
    assert parse_idempotency_key(good) == (
        "d8f05c04-4b0f-4e28-9d87-95c88e6c6a09", 2)

    for bad in ("partner:abc:2", "other:abc:2:handover",
                "partner:abc:x:handover", "partner:abc:2:withdrawal"):
        assert not pattern.match(bad), f"{bad} should not match"
        with pytest.raises(ValueError):
            parse_idempotency_key(bad)


def test_every_documented_path_is_routed(spec):
    """A spec describing an endpoint that does not exist is worse than
    no spec."""
    from django.urls import resolve

    for path in spec["paths"]:
        full = f"/api/v1/grm{path}"
        assert resolve(full) is not None, f"{full} is documented but not routed"
