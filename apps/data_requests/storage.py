"""DRS bundle storage seam.

Sprint 5 (S5-002) shipped an in-process dict (BUNDLE_STORE in
apps.data_requests.bundles) as the bundle persistence layer — fine
for dev/CI, but production needs MinIO (per /CLAUDE.md tech stack).
This module is the seam: BundleStorage Protocol + two
implementations behind a settings flag (DRS_BUNDLE_STORAGE).

    DRS_BUNDLE_STORAGE=memory -> InMemoryBundleStorage   (default)
    DRS_BUNDLE_STORAGE=minio  -> MinIOBundleStorage      (placeholder)

The MinIO client lands when bucket creds + endpoint config arrive
(DRS-O-02). Until then the live class raises NotImplementedError with
a pointer to the open item — same defer-external-deps pattern as
S3-006 IDV LiveNiraClient.

Callers never import a concrete class — they go through
get_bundle_storage() so the swap is a one-line config change at
deploy time.
"""

from __future__ import annotations

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


# Module-level singletons. Tests use _reset_for_tests() on the memory
# backend between cases; production has a single MinIOBundleStorage
# instance per process.
_MEMORY_BACKEND = InMemoryBundleStorage()
_MINIO_BACKEND = MinIOBundleStorage()


def get_bundle_storage() -> BundleStorage:
    """Factory honouring settings.DRS_BUNDLE_STORAGE. The choice is
    read at each call so test code can override settings per-test."""
    backend = (getattr(settings, "DRS_BUNDLE_STORAGE", "memory") or "").lower()
    if backend == "minio":
        return _MINIO_BACKEND
    if backend == "memory":
        return _MEMORY_BACKEND
    raise ValueError(
        f"DRS_BUNDLE_STORAGE={backend!r} unknown; expected 'memory' or 'minio'",
    )
