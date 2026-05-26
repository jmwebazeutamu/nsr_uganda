"""Evidence file storage for Open-CR documents (CR-modal slice 3).

Mirrors `apps.data_requests.storage` — same Protocol + three backends
(InMemory / File / MinIO-stub). Content-addressable by SHA-256, so the
same document uploaded twice collapses to one stored blob.

Selection:
    UPD_EVIDENCE_STORAGE=memory  -> InMemoryEvidenceStorage (tests)
    UPD_EVIDENCE_STORAGE=file    -> FileEvidenceStorage     (dev default)
    UPD_EVIDENCE_STORAGE=minio   -> MinIOEvidenceStorage    (NotImplementedError stub)

The MinIO backend lands when CHB-O-? closes (bucket creds + endpoint).
Until then, prod deploys override UPD_EVIDENCE_DIR to a mounted volume.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from django.conf import settings


class EvidenceStorage(Protocol):
    def put(self, content_sha256: str, body: bytes) -> None: ...
    def get(self, content_sha256: str) -> bytes | None: ...
    def exists(self, content_sha256: str) -> bool: ...


class InMemoryEvidenceStorage:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put(self, content_sha256: str, body: bytes) -> None:
        self._store.setdefault(content_sha256, body)

    def get(self, content_sha256: str) -> bytes | None:
        return self._store.get(content_sha256)

    def exists(self, content_sha256: str) -> bool:
        return content_sha256 in self._store

    def _reset_for_tests(self) -> None:
        self._store.clear()


class FileEvidenceStorage:
    """Disk-backed store. Files at `<evidence_dir>/<sha>.bin`. Atomic
    writes via temp-then-rename. Filenames are validated to be hex
    digests so a malformed key can't escape the dir.
    """

    def __init__(self, evidence_dir: str | Path | None = None) -> None:
        self._dir = Path(evidence_dir) if evidence_dir else None

    def _resolve_dir(self) -> Path:
        if self._dir is not None:
            d = self._dir
        else:
            d = Path(
                getattr(settings, "UPD_EVIDENCE_DIR", None)
                or (Path(settings.BASE_DIR) / ".upd-evidence"),
            )
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, content_sha256: str) -> Path:
        if not content_sha256 or not all(
            c in "0123456789abcdef" for c in content_sha256.lower()
        ):
            raise ValueError(f"content_sha256 must be hex; got {content_sha256!r}")
        if not (1 <= len(content_sha256) <= 128):
            raise ValueError(f"content_sha256 length out of range: {len(content_sha256)}")
        return self._resolve_dir() / f"{content_sha256.lower()}.bin"

    def put(self, content_sha256: str, body: bytes) -> None:
        path = self._path(content_sha256)
        if path.exists():
            return  # content-addressable
        tmp = path.with_suffix(".bin.tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)

    def get(self, content_sha256: str) -> bytes | None:
        try:
            path = self._path(content_sha256)
        except ValueError:
            return None
        if not path.exists():
            return None
        return path.read_bytes()

    def exists(self, content_sha256: str) -> bool:
        try:
            return self._path(content_sha256).exists()
        except ValueError:
            return False

    def _reset_for_tests(self) -> None:
        d = self._resolve_dir()
        for p in d.glob("*.bin"):
            p.unlink(missing_ok=True)
        for p in d.glob("*.bin.tmp"):
            p.unlink(missing_ok=True)


class MinIOEvidenceStorage:
    """Production stub. Replace with a real S3-compatible client once
    the bucket + creds are provisioned. Until then, leaving this class
    raises clearly so a misconfigured deploy can't silently swallow
    uploads."""

    def put(self, content_sha256: str, body: bytes) -> None:
        raise NotImplementedError(
            "MinIOEvidenceStorage is not wired yet — set UPD_EVIDENCE_STORAGE=file "
            "for dev or wait for the production hardening slice.",
        )

    def get(self, content_sha256: str) -> bytes | None:
        raise NotImplementedError("MinIOEvidenceStorage is not wired yet.")

    def exists(self, content_sha256: str) -> bool:
        raise NotImplementedError("MinIOEvidenceStorage is not wired yet.")


_MEMORY_BACKEND = InMemoryEvidenceStorage()
_FILE_BACKEND = FileEvidenceStorage()
_MINIO_BACKEND = MinIOEvidenceStorage()


def get_evidence_storage() -> EvidenceStorage:
    """Resolve the active backend via settings.UPD_EVIDENCE_STORAGE."""
    name = getattr(settings, "UPD_EVIDENCE_STORAGE", "file")
    if name == "memory":
        return _MEMORY_BACKEND
    if name == "minio":
        return _MINIO_BACKEND
    return _FILE_BACKEND


# Per-file + total size guards. base64-in-JSON has ~33% overhead so
# the raw 5 MB / 15 MB caps translate to ~6.7 MB / 20 MB on the wire.
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_FILES = 3
ALLOWED_MIME_TYPES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/webp",
})
