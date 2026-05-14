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
    """Column encrypted via apps.security.encryption (Fernet today; KMS
    envelope-encryption swap-in for production per NSR-O-04).

    Reads return plaintext bytes; writes accept plaintext bytes (or str
    which is utf-8 encoded). On-disk the column holds Fernet ciphertext.
    """

    description = "Encrypted column (Fernet today; KMS-backed in production)"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        from apps.security.encryption import decrypt
        return decrypt(bytes(value))

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.encode("utf-8")
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"EncryptedBinaryField expects bytes or str, got {type(value).__name__}"
            )
        from apps.security.encryption import encrypt
        return encrypt(bytes(value))
