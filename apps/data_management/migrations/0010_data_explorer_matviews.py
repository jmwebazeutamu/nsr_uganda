"""US-DATA-EXP-001 — CREATE MATERIALIZED VIEW DDL for the Data Explorer
matviews.

Per CLAUDE.md raw SQL is allowed only inside data_management and
ingestion_hub. The DATA-EXP app declares matching unmanaged Django
models in apps.data_explorer.matview_models so the ORM can compose
queries against these tables without crossing the no-raw-SQL boundary.

The DDL is guarded on `connection.vendor == 'postgresql'` so the
SQLite test suite + dev databases keep working — the matview models
remain unmanaged and the test fixtures populate them via direct
INSERTs against the underlying table name (Django creates a CHAR(64)
+ misc columns on SQLite because Django can't model a MATERIALIZED
VIEW; that's intentional — tests poke synthetic rows).

Each matview includes a UNIQUE index on the natural key — required by
`REFRESH MATERIALIZED VIEW CONCURRENTLY` and a hard requirement of
ADR-0023.

Reversible: the reverse SQL drops the matviews if the vendor matches.
"""

from __future__ import annotations

from django.db import migrations


# Per ADR-0023 D2 the initial matview set.
_MATVIEWS: list[tuple[str, str, str]] = [
    # (name, definition, unique-index columns)
    (
        "mv_explorer_household_by_subcounty_demographics",
        """
        SELECT
            md5(
                COALESCE(h.sub_region_id::text, '')
                || '|' || COALESCE(h.district_id::text, '')
                || '|' || COALESCE(h.sub_county_id::text, '')
                || '|' || COALESCE(head_sex.code, '')
                || '|' || COALESCE(head_age_band.band, '')
            ) AS id,
            now() AS refreshed_at,
            h.sub_region_id::text AS sub_region_code,
            h.district_id::text AS district_code,
            h.sub_county_id::text AS sub_county_code,
            COALESCE(head_sex.code, '') AS head_sex_code,
            COALESCE(head_age_band.band, '') AS head_age_band,
            COUNT(DISTINCT h.id) AS household_count,
            COUNT(DISTINCT m.id) AS member_count
        FROM data_management_household h
        LEFT JOIN data_management_member m
            ON m.household_id = h.id
            AND m.is_deleted = FALSE
        LEFT JOIN LATERAL (
            SELECT sex AS code
            FROM data_management_member
            WHERE id = h.head_member_id
        ) head_sex ON TRUE
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN dob IS NULL THEN ''
                WHEN EXTRACT(YEAR FROM age(dob)) < 30 THEN '15-29'
                WHEN EXTRACT(YEAR FROM age(dob)) < 45 THEN '30-44'
                WHEN EXTRACT(YEAR FROM age(dob)) < 60 THEN '45-59'
                ELSE '60+'
            END AS band
            FROM data_management_member
            WHERE id = h.head_member_id
        ) head_age_band ON TRUE
        WHERE h.is_deleted = FALSE
        GROUP BY
            h.sub_region_id, h.district_id, h.sub_county_id,
            head_sex.code, head_age_band.band
        """,
        "id",
    ),
    (
        "mv_explorer_household_by_subcounty_pmt",
        """
        SELECT
            md5(
                COALESCE(h.sub_region_id::text, '')
                || '|' || COALESCE(h.district_id::text, '')
                || '|' || COALESCE(h.sub_county_id::text, '')
                || '|' || COALESCE(h.current_vulnerability_band, '')
            ) AS id,
            now() AS refreshed_at,
            h.sub_region_id::text AS sub_region_code,
            h.district_id::text AS district_code,
            h.sub_county_id::text AS sub_county_code,
            COALESCE(h.current_vulnerability_band, '') AS pmt_band,
            COUNT(DISTINCT h.id) AS household_count
        FROM data_management_household h
        WHERE h.is_deleted = FALSE
        GROUP BY
            h.sub_region_id, h.district_id, h.sub_county_id,
            h.current_vulnerability_band
        """,
        "id",
    ),
]


def _apply_postgres(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for name, definition, unique_col in _MATVIEWS:
            cur.execute(
                f"CREATE MATERIALIZED VIEW IF NOT EXISTS {name} AS {definition} "
                f"WITH NO DATA;"
            )
            cur.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {name}_pk "
                f"ON {name} ({unique_col});"
            )


def _drop_postgres(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for name, _, _ in _MATVIEWS:
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name};")


class Migration(migrations.Migration):

    dependencies = [
        ("data_management", "0009_us_s11_044_household_dqa_fields"),
    ]

    operations = [
        migrations.RunPython(_apply_postgres, reverse_code=_drop_postgres),
    ]
