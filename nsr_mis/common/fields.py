"""Framework-level model fields shared across module apps.

Lives in the project package (not in a module app) so all 15 apps can import
without violating the ADR-0001 cross-app import rule.

References:
- ADR-0002 identifier strategy (ULID, encrypted NIN, hash)
"""

from __future__ import annotations

from django.db import models
from ulid import ULID


def generate_ulid() -> str:
    """Generate a new ULID in canonical 26-character Crockford base32, uppercase."""
    return str(ULID())


class ULIDField(models.CharField):
    """CharField pinned to 26 chars with a default ULID generator.

    Used for every externally-visible identifier per ADR-0002. The column is a
    plain CHAR(26) on the DB side; uniqueness/PK is declared by the model.
    """

    description = "26-character Crockford base32 ULID (application-generated)"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 26)
        kwargs.setdefault("default", generate_ulid)
        kwargs.setdefault("editable", False)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        for k in ("max_length", "default", "editable"):
            kwargs.pop(k, None)
        return name, path, args, kwargs


class EncryptedBinaryField(models.BinaryField):
    """Placeholder for a KMS-backed AES-256-GCM encrypted column.

    Sprint 0 stub: stores raw bytes. The encryption boundary is intentionally
    moved into a SEC-owned service (apps.security.kms) and wired in via the
    model's save() and a custom descriptor in a follow-up. Keeping the field
    type stable now means the column type does not churn when KMS lands.
    """

    description = "AES-256-GCM encrypted column (KMS integration pending)"
