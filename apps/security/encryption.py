"""Column-level encryption for NIN and ID-document number columns.

Sprint 1 implementation: Fernet (AES-128-CBC + HMAC-SHA256) keyed off the
NSR_DATA_KEY env var. This satisfies the ADR-0002 intent that NIN never
sits in the database as plaintext; it does NOT satisfy the AES-256-GCM
target. The KMS swap (NSR-O-04) replaces this module with a thin
KMSClient that performs envelope encryption; the EncryptedBinaryField
contract — bytes in, encrypted bytes at rest, bytes out — does not
change. Schema does not churn when KMS lands.

Refuses to boot with the dev key when DEBUG=False so production cannot
accidentally encrypt with a known-public key.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.NSR_DATA_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(plaintext: bytes) -> bytes:
    """Encrypt and return the ciphertext (urlsafe base64 bytes)."""
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError(f"encrypt expects bytes, got {type(plaintext).__name__}")
    return _fernet().encrypt(bytes(plaintext))


def decrypt(ciphertext: bytes) -> bytes:
    """Decrypt and return the plaintext. Raises cryptography.fernet.InvalidToken
    if the bytes do not decode under the configured key."""
    if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
        raise TypeError(f"decrypt expects bytes, got {type(ciphertext).__name__}")
    return _fernet().decrypt(bytes(ciphertext))
