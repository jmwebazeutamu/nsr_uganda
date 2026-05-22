"""DRS bundle storage seam.

Sprint 5 (S5-002) shipped an in-process dict as the bundle layer —
fine for unit tests, broken in any real workflow because the bytes
evaporated whenever the Django process restarted (BUG-S27-032). This
module is the seam: BundleStorage Protocol + three implementations
behind settings.DRS_BUNDLE_STORAGE.

    DRS_BUNDLE_STORAGE=file   -> FileBundleStorage       (default)
    DRS_BUNDLE_STORAGE=memory -> InMemoryBundleStorage   (tests only)
    DRS_BUNDLE_STORAGE=minio  -> MinIOBundleStorage      (placeholder)

`file` writes to `settings.DRS_BUNDLE_DIR` (defaults to
`<BASE_DIR>/.drs-bundles/`) keyed by `<sha>.ndjson`. Survives
restarts; works on every dev box without extra infra.

The MinIO client lands when bucket creds + endpoint config arrive
(DRS-O-02). Until then the live class raises NotImplementedError with
a pointer to the open item — same defer-external-deps pattern as
S3-006 IDV LiveNiraClient.

Callers never import a concrete class — they go through
get_bundle_storage() so the swap is a one-line config change at
deploy time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from django.conf import settings


class BundleStorage(Protocol):
    """Contract every bundle storage backend honours."""

    def put(self, manifest_sha256: str, body: bytes) -> None:
        """Persist the bundle bytes keyed by their manifest SHA-256.
        Idempotent — re-puts of the same hash are safe (content-
        addressable: identical bytes are guaranteed by the hash)."""

    def get(self, manifest_sha256: str) -> bytes | None:
        """Return the bundle bytes for `manifest_sha256`, or None when
        no bundle is stored under that hash."""

    def exists(self, manifest_sha256: str) -> bool:
        """Cheap check used by health probes and the partner-side
        signed-URL handler before issuing a download token."""


class InMemoryBundleStorage:
    """Default backend. Keyed by manifest_sha256 in a module-level
    dict — content-addressable, so re-puts of identical bytes collapse
    to a single entry. Reset between test runs via _reset_for_tests()."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put(self, manifest_sha256: str, body: bytes) -> None:
        self._store.setdefault(manifest_sha256, body)

    def get(self, manifest_sha256: str) -> bytes | None:
        return self._store.get(manifest_sha256)

    def exists(self, manifest_sha256: str) -> bool:
        return manifest_sha256 in self._store

    def _reset_for_tests(self) -> None:
        self._store.clear()


class FileBundleStorage:
    """Disk-backed bundle store. Writes each bundle to
    `<bundles_dir>/<sha>.ndjson`; reads pull bytes back. Content-
    addressable, so a put for an existing sha is a no-op. Default
    dev backend — survives `manage.py runserver` restarts so the
    partner-portal download path works after `/render-and-deliver/`.

    Safety: bundle dir is created on first use. Filenames are pure
    hex digests (validated upstream by DRS-O-PREVIEW) so there's no
    path traversal surface — but we still anchor with the dir +
    enforce `.ndjson` to keep accidents impossible.
    """

    def __init__(self, bundles_dir: str | Path | None = None) -> None:
        # Per-instance dir — tests can spin a fresh tmpdir-backed
        # storage by constructing this class directly. The factory
        # below resolves the production dir from settings.
        self._dir = Path(bundles_dir) if bundles_dir else None

    def _resolve_dir(self) -> Path:
        # Late-bind to settings so tests can override DRS_BUNDLE_DIR
        # per-test via the settings fixture. The configured value
        # takes precedence over the instance-level default.
        if self._dir is not None:
            d = self._dir
        else:
            d = Path(getattr(settings, "DRS_BUNDLE_DIR", None)
                     or (Path(settings.BASE_DIR) / ".drs-bundles"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, manifest_sha256: str) -> Path:
        # Only hex digits — refuse anything else so a malformed input
        # can't escape the bundle dir. SHA-256 hex is 64 chars; we
        # allow shorter for forwards compatibility but bound at 128.
        if not manifest_sha256 or not all(c in "0123456789abcdef" for c in manifest_sha256.lower()):
            raise ValueError(f"manifest_sha256 must be hex; got {manifest_sha256!r}")
        if not (1 <= len(manifest_sha256) <= 128):
            raise ValueError(f"manifest_sha256 length out of range: {len(manifest_sha256)}")
        return self._resolve_dir() / f"{manifest_sha256.lower()}.ndjson"

    def put(self, manifest_sha256: str, body: bytes) -> None:
        path = self._path(manifest_sha256)
        if path.exists():
            return  # content-addressable; identical bytes by construction.
        # Atomic write — temp-then-rename so a crashed put never
        # leaves a half-written .ndjson in the dir.
        tmp = path.with_suffix(".ndjson.tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)

    def get(self, manifest_sha256: str) -> bytes | None:
        try:
            path = self._path(manifest_sha256)
        except ValueError:
            return None
        if not path.exists():
            return None
        return path.read_bytes()

    def exists(self, manifest_sha256: str) -> bool:
        try:
            return self._path(manifest_sha256).exists()
        except ValueError:
            return False

    def _reset_for_tests(self) -> None:
        d = self._resolve_dir()
        for p in d.glob("*.ndjson"):
            p.unlink(missing_ok=True)
        for p in d.glob("*.ndjson.tmp"):
            p.unlink(missing_ok=True)


class MinIOBundleStorage:
    """Production backend. Wiring lands when DRS-O-02 closes (MinIO
    bucket provisioned at NITA-U + creds in the secrets manager).

    The seam exists so call sites never grow a conditional 'if memory
    else minio' branch; when the credentials land, this class gains
    an `minio.Minio` client instance and bodies for the three methods,
    and every caller picks it up by flipping DRS_BUNDLE_STORAGE=minio
    in the environment.
    """

    def put(self, manifest_sha256: str, body: bytes) -> None:
        raise NotImplementedError(
            "MinIOBundleStorage is not wired yet — bucket creds are "
            "pending (DRS-O-02). Run with DRS_BUNDLE_STORAGE=memory "
            "until the integration lands.",
        )

    def get(self, manifest_sha256: str) -> bytes | None:
        raise NotImplementedError(
            "MinIOBundleStorage is not wired yet (DRS-O-02).",
        )

    def exists(self, manifest_sha256: str) -> bool:
        raise NotImplementedError(
            "MinIOBundleStorage is not wired yet (DRS-O-02).",
        )


# Module-level singletons. Tests use _reset_for_tests() between
# cases; production has a single backend instance per process.
_MEMORY_BACKEND = InMemoryBundleStorage()
_FILE_BACKEND = FileBundleStorage()
_MINIO_BACKEND = MinIOBundleStorage()


def get_bundle_storage() -> BundleStorage:
    """Factory honouring settings.DRS_BUNDLE_STORAGE. The choice is
    read at each call so test code can override settings per-test."""
    backend = (getattr(settings, "DRS_BUNDLE_STORAGE", "file") or "").lower()
    if backend == "minio":
        return _MINIO_BACKEND
    if backend == "memory":
        return _MEMORY_BACKEND
    if backend == "file":
        return _FILE_BACKEND
    raise ValueError(
        f"DRS_BUNDLE_STORAGE={backend!r} unknown; "
        "expected 'file', 'memory', or 'minio'",
    )
