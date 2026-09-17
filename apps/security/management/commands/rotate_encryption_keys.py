"""Re-encrypt every column-level secret under a new NSR_DATA_KEY, and
recompute Member.nin_hash under a new NSR_NIN_PEPPER.

Why this exists
---------------
`apps/security/checks.py` refuses to boot with DEBUG=False while
NSR_DATA_KEY or NSR_NIN_PEPPER still hold their dev defaults — the
values published in `.env.example` and therefore in git history. A
production deployment seeded from a dev database therefore cannot simply
carry the dev keys across: the app will not start. Nor can it just adopt
fresh keys, because every existing ciphertext was written under the old
one and would become permanently unreadable.

This command is the bridge. It reads each encrypted column under the OLD
key and rewrites it under the CURRENT (new) one, in place.

How the key swap works
----------------------
`EncryptedBinaryField.from_db_value` decrypts **as the query is
materialised**, not when the attribute is touched. So simply reading a
row while the new key is active raises InvalidToken before any handler
could catch it, and wrapping attribute access in try/except does not
help. Two ORM-level moves avoid that, with no raw SQL (which CLAUDE.md
confines to `data_management` and `ingestion_hub` anyway):

  * READ — `Cast(field, BinaryField())`. BinaryField defines no
    `from_db_value`, so the ciphertext comes back untouched and this
    command decrypts it explicitly with the old key it was given.
  * WRITE — `.defer(<encrypted fields>)`. Deferred columns are not
    selected, so nothing is decrypted while loading the instance; the
    plaintext is then assigned and saved, and `get_prep_value` encrypts
    it under the current (new) key.

Deferred fields are only ever assigned here, never read back — reading
one would trigger a refresh query and decrypt under the wrong key.

Columns are discovered from the Django app registry rather than listed
by hand, so a future eighth encrypted column is picked up automatically
instead of being silently skipped.

Idempotent: a row that already decrypts under the NEW key is left alone,
so an interrupted run can simply be repeated.

Usage
-----
    NSR_OLD_DATA_KEY=<old fernet key> \
    NSR_OLD_NIN_PEPPER=<old pepper> \
      python manage.py rotate_encryption_keys --dry-run

Drop --dry-run to commit. NSR_OLD_NIN_PEPPER is only required when
Member rows carry a nin_hash to recompute.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.db.models.functions import Cast
from nsr_mis.common.fields import EncryptedBinaryField


def _encrypted_fields():
    """Every (model, [field names]) pair carrying an EncryptedBinaryField.

    Discovered from the app registry so the command cannot drift out of
    date against the schema.
    """
    found = []
    for model in django_apps.get_models():
        names = [
            f.name for f in model._meta.get_fields()
            if isinstance(f, EncryptedBinaryField)
        ]
        if names:
            found.append((model, sorted(names)))
    return sorted(found, key=lambda pair: pair[0]._meta.label)


#: Marker for a value that decrypts under neither key.
UNREADABLE = object()
#: Marker for a value already written under the new key.
ALREADY_CURRENT = object()


def _classify(raw, old_fernet, new_fernet):
    """Return plaintext bytes, ALREADY_CURRENT, or UNREADABLE."""
    if raw is None:
        return None
    raw = bytes(raw)
    try:
        return old_fernet.decrypt(raw)
    except InvalidToken:
        pass
    try:
        new_fernet.decrypt(raw)
        return ALREADY_CURRENT
    except InvalidToken:
        return UNREADABLE


class Command(BaseCommand):
    help = (
        "Re-encrypt all EncryptedBinaryField columns under the current "
        "NSR_DATA_KEY, reading them with NSR_OLD_DATA_KEY. Recomputes "
        "Member.nin_hash when NSR_OLD_NIN_PEPPER is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Rows held in memory (as plaintext) per transaction.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        batch_size = opts["batch_size"]

        old_key = os.environ.get("NSR_OLD_DATA_KEY", "").strip()
        if not old_key:
            raise CommandError(
                "NSR_OLD_DATA_KEY is not set. It must hold the Fernet key the "
                "existing ciphertext was written under."
            )
        new_key = settings.NSR_DATA_KEY
        if isinstance(new_key, bytes):
            new_key = new_key.decode()
        if old_key == new_key:
            raise CommandError(
                "NSR_OLD_DATA_KEY equals the current NSR_DATA_KEY — nothing to "
                "rotate. Set NSR_DATA_KEY to the NEW key before running."
            )
        # Fail before touching data if the new key is malformed.
        try:
            Fernet(new_key.encode())
            Fernet(old_key.encode())
        except (ValueError, TypeError) as exc:
            raise CommandError(f"invalid Fernet key: {exc}") from exc

        old_pepper = os.environ.get("NSR_OLD_NIN_PEPPER", "").strip()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written"))

        totals = {"rotated": 0, "already_new": 0, "undecryptable": 0}
        old_fernet = Fernet(old_key.encode())
        new_fernet = Fernet(new_key.encode())

        for model, field_names in _encrypted_fields():
            label = model._meta.label
            manager = model._default_manager
            if not manager.exists():
                self.stdout.write(f"  {label}: no rows, skipped")
                continue

            rotated = already = bad = 0

            # Cast() to a plain BinaryField so the ciphertext is returned
            # as-is instead of being decrypted under the wrong key.
            annotations = {
                f"_raw_{f}": Cast(f, output_field=models.BinaryField())
                for f in field_names
            }
            rows = list(
                manager.annotate(**annotations)
                .values("pk", *annotations.keys())
                .order_by("pk")
            )

            for start_i in range(0, len(rows), batch_size):
                chunk = rows[start_i:start_i + batch_size]
                plaintext = {}
                for row in chunk:
                    vals = {}
                    for f in field_names:
                        vals[f] = _classify(row[f"_raw_{f}"], old_fernet, new_fernet)
                    plaintext[row["pk"]] = vals

                if dry_run:
                    for vals in plaintext.values():
                        for v in vals.values():
                            if v is UNREADABLE:
                                bad += 1
                            elif v is ALREADY_CURRENT:
                                already += 1
                            elif v is not None:
                                rotated += 1
                    continue

                pks = [row["pk"] for row in chunk]
                with transaction.atomic():
                    # defer() keeps the encrypted columns out of the SELECT,
                    # so loading the instance decrypts nothing. These fields
                    # are assigned below but never read back.
                    for obj in manager.filter(pk__in=pks).defer(*field_names):
                        dirty = []
                        vals = plaintext[obj.pk]
                        for f in field_names:
                            v = vals[f]
                            if v is UNREADABLE:
                                bad += 1
                            elif v is ALREADY_CURRENT:
                                already += 1
                            elif v is not None:
                                setattr(obj, f, v)
                                dirty.append(f)
                                rotated += 1
                        # Member.nin_hash is SHA-256(pepper || NIN), so a
                        # pepper change invalidates it. Recompute from the
                        # plaintext already in hand rather than leaving a
                        # dead DDUP tier-1 join key behind.
                        nin_plain = vals.get("nin_value")
                        if (
                            label == "data_management.Member"
                            and old_pepper
                            and isinstance(nin_plain, (bytes, bytearray))
                        ):
                            from apps.security.hashing import nin_hash
                            obj.nin_hash = nin_hash(
                                bytes(nin_plain).decode("utf-8", "ignore")
                            )
                            dirty.append("nin_hash")
                        if dirty:
                            obj.save(update_fields=sorted(set(dirty)))

            totals["rotated"] += rotated
            totals["already_new"] += already
            totals["undecryptable"] += bad
            msg = (
                f"  {label}: {rotated} rotated, "
                f"{already} already current, {bad} unreadable"
            )
            self.stdout.write(self.style.ERROR(msg) if bad else msg)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "rotation complete: "
                f"{totals['rotated']} value(s) re-encrypted, "
                f"{totals['already_new']} already current, "
                f"{totals['undecryptable']} unreadable"
            )
        )
        if totals["undecryptable"]:
            raise CommandError(
                f"{totals['undecryptable']} value(s) decrypt under neither the old "
                f"nor the new key — investigate before starting the app."
            )
