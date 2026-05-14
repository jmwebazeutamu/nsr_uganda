"""Audit chain integrity trigger.

Installs a BEFORE INSERT trigger that populates AuditEvent.prev_hash from the
latest row and AuditEvent.self_hash as SHA-256(prev_hash || canonical_payload).
Also installs BEFORE UPDATE and BEFORE DELETE triggers that raise — AuditEvent
is append-only per SAD §8.4 and ADR-0003.

Postgres-only. On other backends (sqlite for local dev) the migration is a
no-op; the hash columns simply stay NULL and the application is responsible
for running against Postgres in any environment that handles real data.
"""

from __future__ import annotations

from django.db import migrations


CREATE_PGCRYPTO = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"


INSTALL_SQL = r"""
CREATE OR REPLACE FUNCTION security_auditevent_chain_hash() RETURNS trigger AS $$
DECLARE
    latest_hash bytea;
    payload text;
BEGIN
    SELECT self_hash INTO latest_hash
      FROM security_auditevent
     ORDER BY occurred_at DESC, id DESC
     LIMIT 1;

    NEW.prev_hash := latest_hash;

    payload := concat_ws(
        '|',
        NEW.id,
        NEW.occurred_at::text,
        NEW.actor_id,
        NEW.actor_kind,
        NEW.action,
        NEW.entity_type,
        NEW.entity_id,
        coalesce(NEW.field_changes::text, ''),
        coalesce(NEW.reason, ''),
        coalesce(host(NEW.ip_address), ''),
        coalesce(NEW.user_agent, '')
    );

    NEW.self_hash := digest(
        coalesce(NEW.prev_hash, ''::bytea) || convert_to(payload, 'UTF8'),
        'sha256'
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER security_auditevent_chain_hash_trg
    BEFORE INSERT ON security_auditevent
    FOR EACH ROW EXECUTE FUNCTION security_auditevent_chain_hash();

CREATE OR REPLACE FUNCTION security_auditevent_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'AuditEvent is append-only; UPDATE/DELETE forbidden';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER security_auditevent_immutable_upd
    BEFORE UPDATE ON security_auditevent
    FOR EACH ROW EXECUTE FUNCTION security_auditevent_immutable();

CREATE TRIGGER security_auditevent_immutable_del
    BEFORE DELETE ON security_auditevent
    FOR EACH ROW EXECUTE FUNCTION security_auditevent_immutable();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS security_auditevent_immutable_del ON security_auditevent;
DROP TRIGGER IF EXISTS security_auditevent_immutable_upd ON security_auditevent;
DROP TRIGGER IF EXISTS security_auditevent_chain_hash_trg ON security_auditevent;
DROP FUNCTION IF EXISTS security_auditevent_immutable();
DROP FUNCTION IF EXISTS security_auditevent_chain_hash();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_PGCRYPTO)
        schema_editor.execute(INSTALL_SQL)


def uninstall(apps, schema_editor):
    # Intentionally do not drop pgcrypto — other modules may use it.
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(install, uninstall),
    ]
