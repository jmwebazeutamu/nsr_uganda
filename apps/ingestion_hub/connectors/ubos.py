"""UBOS bulk connector — one-off historic load (US-114, SAD §4.6.1).

The UBOS mass-enumeration export bootstraps the registry. It arrives
as files, not as an API: US-114 specifies "CSV/JSON bulk export over
SFTP, with checksums verified before landing". The SFTP leg is not
provisioned yet (no host or key exchange agreed with UBOS), so this
first cut reads from a **drop directory on the DIH host** that an
operator, or later an SFTP mirror job, fills. Everything else in the
story — checksum gate, batch pulls, quarantine of malformed rows,
promotion through the normal NSR Unit queue — runs through the same
DIH pipeline Kobo uses.

The three live methods map the Kobo vocabulary onto files:

    test_connection(creds)  -> the drop directory exists and is readable
    list_forms(creds)       -> one "form" per data file in the directory;
                               `deployed` is True only when the file is
                               pullable (checksum sidecar present + matching,
                               or checksums not required)
    pull_submissions(creds, form_id=<file name>)
                            -> yields one raw dict per household row

`credentials` is the dict `connection_test.credentials_for()` builds
from the UbosCredential row:

    {"drop_path": "/srv/nsr/ubos-drop", "require_checksum": True}

File formats accepted (by extension):

    .json   a JSON array of household objects
    .jsonl  one household object per line
    .csv    one household per row; nested keys use dotted headers
            ("geographic.district", "gps_lat"); the member roster is a
            JSON-encoded string in a `members` column

Every row is expected in the **canonical household shape** the DIH
stages (the same dict `submit_walk_in_capture` and the Kobo mapper
produce: `geographic`, `members`, `urban_rural`, `gps_*`, …). A UBOS
export in its native column layout is mapped to that shape by the
MappingRule v1 the story calls for — that mapping is not part of
this module and stays open until UBOS supplies the export dictionary
(DIH-O-xx). Rows missing the two mandatory blocks raise KeyError so
the pipeline quarantines them per AC-DIH-QUARANTINE instead of
staging half a household.

Row identity for landing dedup (US-S11-034) is
`<file sha256[:16]>#<row number>` so a re-pull of the same file skips
rows already landed, while a corrected re-export (different digest)
lands as new rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .base import ConnectionTestResult, register_connector

logger = logging.getLogger(__name__)

DATA_SUFFIXES = (".json", ".jsonl", ".csv")
CHECKSUM_SUFFIX = ".sha256"

# Keys a canonical household row must carry. Anything else is optional
# and left to DQA (AC-MANDATORY etc.) once staged.
REQUIRED_KEYS = ("geographic", "members")


class UbosFileError(ValueError):
    """A drop-directory or file-level problem (missing file, checksum
    mismatch, unreadable). Distinct from a per-row KeyError/ValueError
    so the caller can fail the run instead of quarantining rows."""


# --- Row canonicalisation ------------------------------------------------

def _unflatten(row: dict[str, Any]) -> dict[str, Any]:
    """Turn dotted CSV headers into nested dicts:
    {"geographic.district": "X"} -> {"geographic": {"district": "X"}}."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        parts = key.split(".")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError(f"conflicting CSV headers around {key!r}")
        node[parts[-1]] = value
    return out


def _csv_row_to_raw(row: dict[str, Any]) -> dict[str, Any]:
    """CSV cells are strings; the member roster travels as a JSON
    string in the `members` column. Empty cells are dropped so the
    canonical row does not carry '' for every unused question."""
    cleaned = {k: v for k, v in row.items() if k and v not in (None, "")}
    raw = _unflatten(cleaned)
    members = raw.get("members")
    if isinstance(members, str):
        try:
            raw["members"] = json.loads(members)
        except json.JSONDecodeError as exc:
            raise ValueError(f"members column is not valid JSON: {exc}") from exc
    return raw


def ubos_to_canonical(raw: dict) -> dict:
    """Validate a UBOS row already in the canonical household shape.

    Pure. Raises KeyError for a missing mandatory block and ValueError
    for a malformed one, which the DIH pipeline turns into a
    Quarantine row (standard connector contract).
    """
    if not isinstance(raw, dict):
        raise ValueError(f"row must be an object, got {type(raw).__name__}")
    for key in REQUIRED_KEYS:
        if key not in raw:
            raise KeyError(key)
    geographic = raw["geographic"]
    if not isinstance(geographic, dict) or not geographic:
        raise ValueError("geographic must be a non-empty object")
    members = raw["members"]
    if not isinstance(members, list) or not members:
        raise ValueError("members must be a non-empty list")
    for i, member in enumerate(members, start=1):
        if not isinstance(member, dict):
            raise ValueError(f"members[{i}] must be an object")
        member.setdefault("line_number", i)
    canonical = {k: v for k, v in raw.items() if not k.startswith("_")}
    # Lineage the reviewer can see on the staged record; mirrors the
    # `_source_keys` block the Kobo mapper writes.
    canonical["_source_keys"] = {
        "ubos_file": raw.get("_ubos_file", ""),
        "ubos_file_sha256": raw.get("_ubos_file_sha256", ""),
        "ubos_row": raw.get("_ubos_row"),
    }
    return canonical


# --- File helpers --------------------------------------------------------

def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_checksum(path: Path) -> str | None:
    """Read `<file>.sha256`. Accepts both bare-digest and the
    `sha256sum` "digest  filename" layout. None when absent."""
    sidecar = path.with_name(path.name + CHECKSUM_SUFFIX)
    if not sidecar.is_file():
        return None
    first = sidecar.read_text(encoding="utf-8").strip().split()
    return first[0].lower() if first else None


def _data_files(drop: Path) -> list[Path]:
    return sorted(
        p for p in drop.iterdir()
        if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
    )


def _describe(path: Path, *, require_checksum: bool) -> dict[str, Any]:
    """The list_forms row for one data file."""
    expected = _expected_checksum(path)
    actual = _sha256_of(path)
    if expected is None:
        checksum = "missing"
        ready = not require_checksum
    elif expected == actual:
        checksum = "ok"
        ready = True
    else:
        checksum = "mismatch"
        ready = False
    return {
        "uid": path.name,
        "name": f"{path.name} ({path.stat().st_size:,} bytes, checksum {checksum})",
        "asset_type": path.suffix.lower().lstrip("."),
        "deployed": ready,
        "sha256": actual,
        "checksum": checksum,
    }


def _iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise UbosFileError(f"{path.name}: JSON export must be an array of households")
        yield from data
    elif suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                yield _csv_row_to_raw(row)
    else:  # pragma: no cover — list_forms only offers DATA_SUFFIXES
        raise UbosFileError(f"{path.name}: unsupported file type")


# --- Connector -----------------------------------------------------------

class UbosBulkConnector:
    """File-drop implementation of the DIH Connector protocol for the
    UBOS historic load. Registered under the seeded `UBOS-BULK`
    SourceSystem code (scripts/seed_dih_sources.py)."""

    code = "UBOS-BULK"

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _drop(credentials: dict) -> Path:
        drop_path = (credentials or {}).get("drop_path") or ""
        if not drop_path:
            raise UbosFileError("drop_path is not configured")
        drop = Path(drop_path)
        if not drop.is_dir():
            raise UbosFileError(f"drop directory does not exist: {drop}")
        if not os.access(drop, os.R_OK):
            raise UbosFileError(f"drop directory is not readable: {drop}")
        return drop

    @staticmethod
    def _require_checksum(credentials: dict) -> bool:
        return bool((credentials or {}).get("require_checksum", True))

    # -- Connector protocol ---------------------------------------------

    def canonicalize(self, raw: dict) -> dict:
        return ubos_to_canonical(raw)

    # The generic DIH pipeline (stage -> DQA -> IDV -> DDUP -> route)
    # handles the side-effects; nothing UBOS-specific to do per row.
    process = None

    def test_connection(self, credentials: dict) -> ConnectionTestResult:
        """Cheap probe: the drop directory is reachable and readable.
        Reports how many data files are waiting so the operator can
        see at a glance whether the export has arrived."""
        started = time.monotonic()
        try:
            drop = self._drop(credentials)
            files = _data_files(drop)
        except UbosFileError as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )
        return ConnectionTestResult(
            ok=True,
            latency_ms=int((time.monotonic() - started) * 1000),
            server_version=f"drop:{len(files)} file(s)",
        )

    def list_forms(self, credentials: dict) -> list[dict]:
        """One entry per data file. `deployed` doubles as "pullable"
        so the console's form picker (which filters on it) only
        offers files that pass the checksum gate."""
        drop = self._drop(credentials)
        require = self._require_checksum(credentials)
        return [_describe(p, require_checksum=require) for p in _data_files(drop)]

    def pull_submissions(
        self, credentials: dict, *, form_id: str, since: str | None = None,
    ) -> Iterator[dict]:
        """Yield one raw household per row of `form_id` (a file name in
        the drop directory). `since` is accepted for protocol parity
        and ignored — files carry no submission timestamps; landing
        dedup on `_id` makes re-pulls idempotent instead."""
        drop = self._drop(credentials)
        path = drop / Path(form_id).name  # no path traversal out of the drop
        if not path.is_file():
            raise UbosFileError(f"{form_id}: not found in {drop}")
        info = _describe(path, require_checksum=self._require_checksum(credentials))
        if not info["deployed"]:
            raise UbosFileError(
                f"{form_id}: checksum {info['checksum']} — refusing to land "
                "(US-114: checksums verified before landing)",
            )
        digest = info["sha256"]
        for row_no, row in enumerate(_iter_rows(path), start=1):
            if not isinstance(row, dict):
                row = {"_invalid_row": row}
            row["_id"] = f"{digest[:16]}#{row_no}"
            row["_ubos_file"] = path.name
            row["_ubos_file_sha256"] = digest
            row["_ubos_row"] = row_no
            yield row


register_connector(UbosBulkConnector())
