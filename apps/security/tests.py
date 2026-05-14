"""Hashing + encryption tests."""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from apps.security.encryption import decrypt, encrypt
from apps.security.hashing import nin_hash, nin_last4


class TestNinHash:
    def test_deterministic_for_same_input(self):
        assert nin_hash("CM1234567890AB") == nin_hash("CM1234567890AB")

    def test_normalises_case_and_whitespace(self):
        assert nin_hash("cm1234567890ab") == nin_hash("  CM1234567890AB  ")

    def test_different_nins_produce_different_hashes(self):
        assert nin_hash("CM1234567890AB") != nin_hash("CM1234567890AC")

    def test_includes_pepper_so_not_bare_sha256(self):
        import hashlib
        bare = hashlib.sha256(b"CM1234567890AB").digest()
        assert nin_hash("CM1234567890AB") != bare

    def test_returns_32_bytes(self):
        h = nin_hash("CM1234567890AB")
        assert isinstance(h, bytes) and len(h) == 32

    def test_last4_handles_short_input(self):
        assert nin_last4("AB") == "AB"
        assert nin_last4("CM1234567890AB") == "90AB"


class TestEncryption:
    def test_roundtrip(self):
        plaintext = b"CM1234567890AB"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_ciphertext_differs_each_call(self):
        # Fernet uses a random IV per encryption; the ciphertext should
        # not be deterministic even for identical plaintext.
        a = encrypt(b"CM1234567890AB")
        b = encrypt(b"CM1234567890AB")
        assert a != b

    def test_decrypt_rejects_garbage(self):
        with pytest.raises(InvalidToken):
            decrypt(b"not-a-valid-fernet-token")

    def test_encrypt_rejects_str(self):
        with pytest.raises(TypeError):
            encrypt("CM1234567890AB")


class TestEncryptedField:
    """End-to-end through the Django field on a real Member row."""

    def test_member_nin_value_roundtrips_via_field(self, db):
        from datetime import date

        from apps.data_management.models import Household, Member, NinStatus
        from apps.reference_data.models import GeographicUnit

        # Minimal 7-level ladder.
        nodes = {}
        for level, key, parent in [
            ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
            ("county", "c", "d"), ("sub_county", "sc", "c"),
            ("parish", "p", "sc"), ("village", "v", "p"),
        ]:
            nodes[key] = GeographicUnit.objects.create(
                level=level, code=f"E-{key.upper()}", name=key.title(),
                parent=nodes.get(parent), effective_from=date(2026, 1, 1),
            )
        hh = Household.objects.create(
            region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"], county=nodes["c"],
            sub_county=nodes["sc"], parish=nodes["p"], village=nodes["v"], urban_rural="rural",
        )
        plaintext = b"CM1234567890AB"
        m = Member.objects.create(
            household=hh, line_number=1, surname="Okot", first_name="J", sex="M",
            nin_value=plaintext, nin_hash=nin_hash("CM1234567890AB"),
            nin_last4="90AB", nin_status=NinStatus.HAS_CARD,
        )

        fetched = Member.objects.get(pk=m.pk)
        # The descriptor returns the plaintext bytes that went in.
        assert bytes(fetched.nin_value) == plaintext
