"""Tests for the rotate_encryption_keys management command.

This command rewrites every column-level secret in the registry, so it is
exactly the kind of change CLAUDE.md requires tests-first for. The cases
below pin the three behaviours a production run depends on:

  1. ciphertext written under the old key is readable under the new one
     afterwards, with the plaintext unchanged;
  2. nin_hash is recomputed, so the DDUP tier-1 join key still matches a
     freshly computed hash of the same NIN;
  3. a second run is a no-op rather than double-encrypting.
"""

from __future__ import annotations

import base64
import secrets
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.security import encryption
from apps.security.hashing import nin_hash


def _key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture
def old_key():
    return _key()


@pytest.fixture
def new_key():
    return _key()


@pytest.fixture
def household(db):
    """Minimal 7-level geography ladder plus a Household, so Member's
    non-null FKs are satisfied. Mirrors apps/ddup/tests.py."""
    from apps.data_management.models import Household
    from apps.reference_data.models import GeographicUnit

    nodes = {}
    for level, key, parent in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"ROT-{key.upper()}", name=key.title(),
            parent=nodes.get(parent), effective_from=date(2026, 1, 1),
        )
    return Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
        village=nodes["v"], urban_rural="2",
    )


def _make_member(household, nin: str):
    """Create a Member carrying an encrypted NIN under the active key."""
    from apps.data_management.models import Member
    return Member.objects.create(
        household=household,
        line_number=1,
        surname="Rotate",
        first_name="Test",
        sex="1",
        nin_value=nin.encode(),
        nin_hash=nin_hash(nin),
        nin_last4=nin[-4:],
        nin_status="1",
    )


@pytest.mark.django_db
def test_rotates_nin_to_the_new_key(settings, monkeypatch, household, old_key, new_key):

    nin = "CM90012345ABCD"

    settings.NSR_DATA_KEY = old_key
    encryption._fernet.cache_clear()
    member = _make_member(household, nin)

    # Deploy-time state: the app now runs with the NEW key, and the old
    # one is supplied only to the command.
    settings.NSR_DATA_KEY = new_key
    encryption._fernet.cache_clear()
    monkeypatch.setenv("NSR_OLD_DATA_KEY", old_key)

    call_command("rotate_encryption_keys", stdout=StringIO())

    encryption._fernet.cache_clear()
    member.refresh_from_db()
    assert bytes(member.nin_value) == nin.encode()


@pytest.mark.django_db
def test_recomputes_nin_hash_under_the_new_pepper(
    settings, monkeypatch, household, old_key, new_key,
):

    nin = "CM90012345ABCD"
    old_pepper, new_pepper = "old-pepper-value", "new-pepper-value"

    settings.NSR_DATA_KEY = old_key
    settings.NSR_NIN_PEPPER = old_pepper
    encryption._fernet.cache_clear()
    member = _make_member(household, nin)
    stale_hash = bytes(member.nin_hash)

    settings.NSR_DATA_KEY = new_key
    settings.NSR_NIN_PEPPER = new_pepper
    encryption._fernet.cache_clear()
    monkeypatch.setenv("NSR_OLD_DATA_KEY", old_key)
    monkeypatch.setenv("NSR_OLD_NIN_PEPPER", old_pepper)

    call_command("rotate_encryption_keys", stdout=StringIO())

    member.refresh_from_db()
    # The join key must match a hash computed fresh under the new pepper,
    # and must no longer be the old one.
    assert bytes(member.nin_hash) == nin_hash(nin)
    assert bytes(member.nin_hash) != stale_hash


@pytest.mark.django_db
def test_second_run_is_a_no_op(settings, monkeypatch, household, old_key, new_key):
    nin = "CM90012345ABCD"

    settings.NSR_DATA_KEY = old_key
    encryption._fernet.cache_clear()
    member = _make_member(household, nin)

    settings.NSR_DATA_KEY = new_key
    encryption._fernet.cache_clear()
    monkeypatch.setenv("NSR_OLD_DATA_KEY", old_key)

    call_command("rotate_encryption_keys", stdout=StringIO())
    out = StringIO()
    call_command("rotate_encryption_keys", stdout=out)

    # Nothing left to rotate, and the value survived both passes intact.
    assert "0 value(s) re-encrypted" in out.getvalue()
    encryption._fernet.cache_clear()
    member.refresh_from_db()
    assert bytes(member.nin_value) == nin.encode()


@pytest.mark.django_db
def test_refuses_when_old_key_is_missing(settings, monkeypatch, new_key):
    settings.NSR_DATA_KEY = new_key
    monkeypatch.delenv("NSR_OLD_DATA_KEY", raising=False)
    with pytest.raises(CommandError, match="NSR_OLD_DATA_KEY is not set"):
        call_command("rotate_encryption_keys", stdout=StringIO())


@pytest.mark.django_db
def test_refuses_when_old_and_new_keys_are_identical(settings, monkeypatch, new_key):
    settings.NSR_DATA_KEY = new_key
    monkeypatch.setenv("NSR_OLD_DATA_KEY", new_key)
    with pytest.raises(CommandError, match="nothing to rotate"):
        call_command("rotate_encryption_keys", stdout=StringIO())


@pytest.mark.django_db
def test_dry_run_writes_nothing(settings, monkeypatch, household, old_key, new_key):
    nin = "CM90012345ABCD"

    settings.NSR_DATA_KEY = old_key
    encryption._fernet.cache_clear()
    member = _make_member(household, nin)

    settings.NSR_DATA_KEY = new_key
    encryption._fernet.cache_clear()
    monkeypatch.setenv("NSR_OLD_DATA_KEY", old_key)

    out = StringIO()
    call_command("rotate_encryption_keys", "--dry-run", stdout=out)
    assert "DRY RUN" in out.getvalue()

    # Still only readable under the OLD key -> nothing was rewritten.
    settings.NSR_DATA_KEY = old_key
    encryption._fernet.cache_clear()
    member.refresh_from_db()
    assert bytes(member.nin_value) == nin.encode()
