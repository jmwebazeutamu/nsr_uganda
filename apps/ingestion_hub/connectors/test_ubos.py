"""UbosBulkConnector unit tests (US-114 — UBOS bulk connector, file-drop cut).

Pure-filesystem tests: every case builds its own drop directory under
`tmp_path`, so nothing here touches the database or the network.

Covered:
- registry code
- canonicalize: passthrough validation, missing/invalid blocks,
  lineage block from the pull metadata
- CSV unflattening (dotted headers, JSON members column)
- test_connection: ok / missing / unreadable directory
- list_forms: checksum ok / mismatch / missing under both policies
- pull_submissions: row identity, checksum gate, path traversal,
  JSON / JSONL / CSV readers
"""

from __future__ import annotations

import csv
import hashlib
import json

import pytest

from apps.ingestion_hub.connectors.base import get_connector
from apps.ingestion_hub.connectors.ubos import (
    UbosBulkConnector,
    UbosFileError,
    ubos_to_canonical,
)

GEO = {
    "region": "T-R", "sub_region": "T-SR", "district": "T-D",
    "county": "T-C", "sub_county": "T-SC", "parish": "T-P", "village": "T-V",
}


def _household(head: str = "Okot") -> dict:
    return {
        "geographic": dict(GEO),
        "urban_rural": "rural",
        "gps_lat": "1.2", "gps_lng": "33.0",
        "members": [
            {"surname": head, "first_name": "James", "sex": "1",
             "relationship_to_head": "01", "is_head": True},
            {"surname": head, "first_name": "Mary", "sex": "2",
             "relationship_to_head": "02"},
        ],
    }


def _write(path, content: str, *, sidecar: bool = True, wrong: bool = False) -> str:
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if sidecar:
        stored = ("0" * 64) if wrong else digest
        # sha256sum layout: "<digest>  <name>"
        path.with_name(path.name + ".sha256").write_text(f"{stored}  {path.name}\n")
    return digest


@pytest.fixture
def drop(tmp_path):
    d = tmp_path / "ubos-drop"
    d.mkdir()
    return d


@pytest.fixture
def creds(drop):
    return {"drop_path": str(drop), "require_checksum": True}


@pytest.fixture
def connector():
    return UbosBulkConnector()


class TestRegistry:
    def test_registered_under_seeded_code(self):
        impl = get_connector("UBOS-BULK")
        assert isinstance(impl, UbosBulkConnector)
        # Live methods present; push-only `process` intentionally None.
        assert impl.process is None
        assert impl.list_forms is not None
        assert impl.pull_submissions is not None


class TestCanonicalize:
    def test_passthrough_adds_line_numbers_and_lineage(self):
        raw = _household()
        raw.update({"_id": "abc#1", "_ubos_file": "x.json",
                    "_ubos_file_sha256": "ff", "_ubos_row": 1})
        out = ubos_to_canonical(raw)
        assert out["geographic"] == GEO
        assert [m["line_number"] for m in out["members"]] == [1, 2]
        assert out["_source_keys"] == {
            "ubos_file": "x.json", "ubos_file_sha256": "ff", "ubos_row": 1,
        }
        # Pull metadata does not leak into the canonical payload.
        assert "_id" not in out and "_ubos_row" not in out

    def test_missing_geographic_raises_keyerror(self):
        raw = _household()
        del raw["geographic"]
        with pytest.raises(KeyError):
            ubos_to_canonical(raw)

    def test_empty_members_raises_valueerror(self):
        raw = _household()
        raw["members"] = []
        with pytest.raises(ValueError, match="members"):
            ubos_to_canonical(raw)

    def test_non_object_row_raises_valueerror(self):
        with pytest.raises(ValueError, match="object"):
            ubos_to_canonical(["not", "a", "dict"])  # type: ignore[arg-type]


class TestTestConnection:
    def test_ok_reports_file_count(self, connector, drop, creds):
        _write(drop / "a.json", json.dumps([_household()]))
        _write(drop / "b.csv", "geographic.district,members\n")
        result = connector.test_connection(creds)
        assert result.ok is True
        assert result.server_version == "drop:2 file(s)"
        assert result.latency_ms >= 0

    def test_missing_directory_fails(self, connector, tmp_path):
        result = connector.test_connection({"drop_path": str(tmp_path / "nope")})
        assert result.ok is False
        assert "does not exist" in result.error

    def test_unconfigured_path_fails(self, connector):
        result = connector.test_connection({})
        assert result.ok is False
        assert "not configured" in result.error


class TestListForms:
    def test_checksum_states(self, connector, drop, creds):
        _write(drop / "ok.json", json.dumps([_household()]))
        _write(drop / "bad.json", json.dumps([_household()]), wrong=True)
        _write(drop / "nosidecar.jsonl", json.dumps(_household()) + "\n", sidecar=False)
        (drop / "README.txt").write_text("ignored")
        forms = {f["uid"]: f for f in connector.list_forms(creds)}
        assert set(forms) == {"ok.json", "bad.json", "nosidecar.jsonl"}
        assert forms["ok.json"]["deployed"] is True
        assert forms["ok.json"]["checksum"] == "ok"
        assert forms["bad.json"]["deployed"] is False
        assert forms["bad.json"]["checksum"] == "mismatch"
        assert forms["nosidecar.jsonl"]["deployed"] is False
        assert forms["nosidecar.jsonl"]["checksum"] == "missing"
        assert forms["ok.json"]["asset_type"] == "json"

    def test_missing_sidecar_allowed_when_not_required(self, connector, drop, creds):
        _write(drop / "nosidecar.json", json.dumps([_household()]), sidecar=False)
        _write(drop / "bad.json", json.dumps([_household()]), wrong=True)
        forms = {f["uid"]: f for f in connector.list_forms({**creds, "require_checksum": False})}
        assert forms["nosidecar.json"]["deployed"] is True
        # A *wrong* sidecar still blocks — the policy only relaxes absence.
        assert forms["bad.json"]["deployed"] is False


class TestPullSubmissions:
    def test_json_rows_carry_identity_and_lineage(self, connector, drop, creds):
        digest = _write(drop / "hh.json", json.dumps([_household("A"), _household("B")]))
        rows = list(connector.pull_submissions(creds, form_id="hh.json"))
        assert [r["_id"] for r in rows] == [f"{digest[:16]}#1", f"{digest[:16]}#2"]
        assert rows[0]["_ubos_file"] == "hh.json"
        assert rows[0]["_ubos_file_sha256"] == digest
        assert rows[1]["_ubos_row"] == 2
        assert rows[1]["members"][0]["surname"] == "B"

    def test_jsonl_reader(self, connector, drop, creds):
        content = "\n".join(json.dumps(_household(h)) for h in ("A", "B", "C")) + "\n\n"
        _write(drop / "hh.jsonl", content)
        rows = list(connector.pull_submissions(creds, form_id="hh.jsonl"))
        assert len(rows) == 3

    def test_csv_reader_unflattens_and_parses_members(self, connector, drop, creds):
        path = drop / "hh.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["geographic.district", "geographic.parish", "urban_rural",
                        "gps_lat", "members", "address_narrative"])
            w.writerow(["T-D", "T-P", "rural", "1.2",
                        json.dumps([{"surname": "Okot", "first_name": "J", "sex": "1"}]), ""])
        _write(path, path.read_text(encoding="utf-8"))
        rows = list(connector.pull_submissions(creds, form_id="hh.csv"))
        assert rows[0]["geographic"] == {"district": "T-D", "parish": "T-P"}
        assert rows[0]["members"][0]["surname"] == "Okot"
        assert "address_narrative" not in rows[0]  # empty cell dropped
        canonical = ubos_to_canonical(rows[0])
        assert canonical["members"][0]["line_number"] == 1

    def test_csv_bad_members_json_is_a_row_error(self, connector, drop, creds):
        path = drop / "hh.csv"
        path.write_text("geographic.district,members\nT-D,not-json\n", encoding="utf-8")
        _write(path, path.read_text(encoding="utf-8"))
        with pytest.raises(ValueError, match="members column"):
            list(connector.pull_submissions(creds, form_id="hh.csv"))

    def test_checksum_mismatch_refuses_to_land(self, connector, drop, creds):
        _write(drop / "bad.json", json.dumps([_household()]), wrong=True)
        with pytest.raises(UbosFileError, match="checksum mismatch"):
            list(connector.pull_submissions(creds, form_id="bad.json"))

    def test_missing_sidecar_refused_when_required(self, connector, drop, creds):
        _write(drop / "nosidecar.json", json.dumps([_household()]), sidecar=False)
        with pytest.raises(UbosFileError, match="checksum missing"):
            list(connector.pull_submissions(creds, form_id="nosidecar.json"))
        rows = list(connector.pull_submissions(
            {**creds, "require_checksum": False}, form_id="nosidecar.json",
        ))
        assert len(rows) == 1

    def test_unknown_file_raises(self, connector, creds):
        with pytest.raises(UbosFileError, match="not found"):
            list(connector.pull_submissions(creds, form_id="ghost.json"))

    def test_path_traversal_is_confined_to_drop(self, connector, drop, creds, tmp_path):
        outside = tmp_path / "secret.json"
        outside.write_text(json.dumps([_household()]))
        # "../secret.json" collapses to "secret.json" inside the drop,
        # which does not exist there — never reads outside the drop.
        with pytest.raises(UbosFileError, match="not found"):
            list(connector.pull_submissions(creds, form_id="../secret.json"))

    def test_non_array_json_is_a_file_error(self, connector, drop, creds):
        _write(drop / "obj.json", json.dumps(_household()))
        with pytest.raises(UbosFileError, match="array"):
            list(connector.pull_submissions(creds, form_id="obj.json"))
