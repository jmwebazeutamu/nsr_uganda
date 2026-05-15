"""DIH connector framework tests — registry + Protocol conformance.

The four shipped connectors (pdm, nusaf, wfp_scope, nira_vital)
must all register against CONNECTOR_REGISTRY at import time. New
connectors that miss this step won't be reachable from the future
generic POST endpoint.
"""

from __future__ import annotations

import pytest

from apps.ingestion_hub.connectors import (
    get_connector,
    register_connector,
    registered_codes,
)


class TestRegistry:
    def test_four_shipped_connectors_registered(self):
        """The four Sprint-3-through-7 connectors should all appear
        in the registry at import time."""
        codes = registered_codes()
        for expected in ("PDM-MIS", "NUSAF-MIS", "WFP-SCOPE", "NIRA-REVERSE"):
            assert expected in codes

    def test_get_connector_returns_instance(self):
        c = get_connector("PDM-MIS")
        assert c is not None
        assert c.code == "PDM-MIS"

    def test_get_connector_unknown_returns_none(self):
        assert get_connector("DOES-NOT-EXIST") is None

    def test_pdm_connector_canonicalize_round_trips(self):
        c = get_connector("PDM-MIS")
        raw = {
            "pdm_household_id": "PDM-2026-X",
            "geographic": {
                "region": "R", "sub_region": "SR", "district": "D",
                "county": "C", "sub_county": "SC", "parish": "P",
                "village": "V",
            },
            "members": [{"role": "head", "surname": "X", "first_name": "Y"}],
        }
        out = c.canonicalize(raw)
        assert out["geographic"]["village"] == "V"
        assert out["_source_keys"]["pdm_household_id"] == "PDM-2026-X"

    def test_nira_reverse_has_a_process_method(self):
        """NIRA reverse-feed exposes process() because the death-event
        path is side-effecting (drives the UPD auto-commit). Others
        leave process=None and run through the generic DIH pipeline."""
        nira = get_connector("NIRA-REVERSE")
        pdm = get_connector("PDM-MIS")
        assert nira.process is not None
        assert pdm.process is None

    def test_register_is_idempotent(self):
        """Re-registering the same code is a no-op — the connectors
        package re-imports cleanly under test re-load conditions."""

        class _DupeConnector:
            code = "PDM-MIS"

            def canonicalize(self, raw):
                return {"DIFFERENT": True}

            process = None

        before = get_connector("PDM-MIS")
        register_connector(_DupeConnector())
        after = get_connector("PDM-MIS")
        # The original instance survives — second registration didn't
        # clobber it.
        assert after is before

    def test_registered_codes_sorted(self):
        codes = registered_codes()
        assert codes == sorted(codes)

    def test_canonicalize_failure_modes_preserved(self):
        """The Protocol-conforming wrappers must NOT swallow the
        canonicalize errors (KeyError / ValueError) — the caller
        relies on them to route to Quarantine."""
        with pytest.raises(KeyError):
            get_connector("PDM-MIS").canonicalize({"members": []})
        with pytest.raises(ValueError, match="unknown NIRA event_type"):
            get_connector("NIRA-REVERSE").canonicalize(
                {"event_type": "marriage", "nin": "CM" + "0" * 12,
                 "event_date": "2026-01-01"},
            )
