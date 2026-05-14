"""Canonical NIN hashing.

Per ADR-0002 (NIN trio): the deterministic join key is SHA-256 of the
normalised NIN combined with a project-wide pepper. The pepper lives in
the NSR_NIN_PEPPER env var; in production it sits in the NITA-U KMS and
rotates per the documented schedule.

Every code path that writes or queries Member.nin_hash MUST go through
nin_hash() — never compute SHA-256 inline. A drift between writers and
readers would silently break DDUP tier-1 discovery (the audit found
exactly this hole at apps/ingestion_hub/services.py:317).
"""

from __future__ import annotations

import hashlib

from django.conf import settings


def _pepper() -> bytes:
    pepper = settings.NSR_NIN_PEPPER
    return pepper.encode() if isinstance(pepper, str) else pepper


def _normalise(nin: str) -> str:
    """Strip surrounding whitespace and force uppercase per NIRA convention."""
    return (nin or "").strip().upper()


def nin_hash(nin: str) -> bytes:
    """Return 32 bytes: SHA-256(pepper || normalised NIN)."""
    return hashlib.sha256(_pepper() + _normalise(nin).encode("utf-8")).digest()


def nin_last4(nin: str) -> str:
    """Return the 4-character masked display suffix per ADR-0002."""
    norm = _normalise(nin)
    return norm[-4:] if len(norm) >= 4 else norm
