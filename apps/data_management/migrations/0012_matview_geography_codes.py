"""The 0010 pair project geographic CODES, not GeographicUnit row ids.

`mv_explorer_household_by_subcounty_demographics` and
`mv_explorer_household_by_subcounty_pmt` were built projecting
`h.sub_region_id::text`, `h.district_id::text` and
`h.sub_county_id::text` into columns named `sub_region_code`,
`district_code` and `sub_county_code`. Those are primary keys:

    sub_region_code | district_code | sub_county_code | household_count
    13532           | 9             | 474             | 3

Every consumer of those columns supplies codes:

  * `query_builder._apply_geographic_scope` maps the request's level to
    exactly these three columns and filters `<column>__in=codes`, where
    the codes are what a caller sends — "101.1.01", not "474".
  * `Household.sub_region_code` (ADR-0005's partition key) holds the
    code, and the matviews are a projection of Household.
  * `mv_explorer_household_shocks_subregion` (migration 0011) holds the
    code.

So every geographically-scoped aggregate against these two datasets has
been matching nothing and returning an empty result — not an error, not
a warning, an empty result that reads as "no households there". Only an
unscoped, national query has ever returned rows.

## Recreate, not replace

Postgres has no CREATE OR REPLACE MATERIALIZED VIEW and the column
expressions change, so each matview is dropped and rebuilt. Verified
before writing this: nothing else in the database depends on either
(`pg_depend` via `pg_rewrite` returns no dependent objects), so the drop
takes nothing with it.

## sub_region_code comes from the denormalised column

`h.sub_region_code` rather than a join to `reference_data_geographicunit`
— it is the column ADR-0005 makes authoritative for routing, the one
ABAC matches, and the one migration 0011 used. District and sub-county
have no denormalised code on Household, so those join through the FK.
Verified on production before the change: 354 households, zero rows
where `sub_region_code` differs from `sub_region.code`, and no nulls in
any of the three FKs.

## NULL becomes ''

The old definitions selected the bare `*_id::text`, so a household with
no sub-county produced NULL in a column the unmanaged model declares as
a non-null CharField. The three columns are now COALESCE'd to '',
matching 0011. Nothing is lost: `__in` never matched NULL either.

## The join couples these matviews to reference_data_geographicunit.code

Postgres records a dependency from a matview to every column it reads,
and refuses `ALTER TABLE ... ALTER COLUMN TYPE` on a column a matview
depends on:

    cannot alter type of a column used by a view or rule
    DETAIL: rule _RETURN on materialized view
            mv_explorer_household_by_subcounty_demographics
            depends on column "code"

`reference_data.0017_alter_geographicunit_code` widens `code` to
varchar(48), so on a database built from scratch this migration must
run after it — hence the explicit dependency below. Without it the
migration graph is free to interleave the two apps and the build fails
partway through, which is how this was found.

That dependency fixes ordering, not the coupling: any FUTURE migration
altering `geographicunit.code` has to drop these matviews first and let
this migration's definitions be re-applied. The durable fix is to
denormalise `district_code` and `sub_county_code` onto Household the
way ADR-0005 already denormalises `sub_region_code`, which removes the
join entirely — a Household schema change and a backfill, so it is
raised as a follow-up rather than done here.

The reverse restores the 0010 definitions verbatim, row ids and all.
"""

from django.db import migrations

_HEAD_SEX = """
        LEFT JOIN LATERAL (
            SELECT sex AS code
            FROM data_management_member
            WHERE id = h.head_member_id
        ) head_sex ON TRUE
"""

_HEAD_AGE_BAND = """
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN date_of_birth IS NULL THEN ''
                WHEN EXTRACT(YEAR FROM age(date_of_birth)) < 30 THEN '15-29'
                WHEN EXTRACT(YEAR FROM age(date_of_birth)) < 45 THEN '30-44'
                WHEN EXTRACT(YEAR FROM age(date_of_birth)) < 60 THEN '45-59'
                ELSE '60+'
            END AS band
            FROM data_management_member
            WHERE id = h.head_member_id
        ) head_age_band ON TRUE
"""

# Join Household to the GeographicUnit rows its district / sub-county FKs
# point at. The FK names one specific (versioned) row, so this cannot
# fan out.
_GEO_JOINS = """
        LEFT JOIN reference_data_geographicunit d ON d.id = h.district_id
        LEFT JOIN reference_data_geographicunit sc ON sc.id = h.sub_county_id
"""

_CODE_KEY = """
                COALESCE(h.sub_region_code, '')
                || '|' || COALESCE(d.code, '')
                || '|' || COALESCE(sc.code, '')
"""

_CODE_COLUMNS = """
            COALESCE(h.sub_region_code, '') AS sub_region_code,
            COALESCE(d.code, '') AS district_code,
            COALESCE(sc.code, '') AS sub_county_code,
"""

_CODE_GROUP_BY = "h.sub_region_code, d.code, sc.code"


# (name, definition) — the corrected, code-projecting pair.
FORWARD: list[tuple[str, str]] = [
    (
        "mv_explorer_household_by_subcounty_demographics",
        f"""
        SELECT
            md5(
                {_CODE_KEY.strip()}
                || '|' || COALESCE(head_sex.code, '')
                || '|' || COALESCE(head_age_band.band, '')
            ) AS id,
            now() AS refreshed_at,
            {_CODE_COLUMNS.strip()}
            COALESCE(head_sex.code, '') AS head_sex_code,
            COALESCE(head_age_band.band, '') AS head_age_band,
            COUNT(DISTINCT h.id) AS household_count,
            COUNT(DISTINCT m.id) AS member_count
        FROM data_management_household h
        {_GEO_JOINS.strip()}
        LEFT JOIN data_management_member m
            ON m.household_id = h.id
            AND m.is_deleted = FALSE
        {_HEAD_SEX.strip()}
        {_HEAD_AGE_BAND.strip()}
        WHERE h.is_deleted = FALSE
        GROUP BY
            {_CODE_GROUP_BY},
            head_sex.code, head_age_band.band
        """,
    ),
    (
        "mv_explorer_household_by_subcounty_pmt",
        f"""
        SELECT
            md5(
                {_CODE_KEY.strip()}
                || '|' || COALESCE(h.current_vulnerability_band, '')
            ) AS id,
            now() AS refreshed_at,
            {_CODE_COLUMNS.strip()}
            COALESCE(h.current_vulnerability_band, '') AS pmt_band,
            COUNT(DISTINCT h.id) AS household_count
        FROM data_management_household h
        {_GEO_JOINS.strip()}
        WHERE h.is_deleted = FALSE
        GROUP BY
            {_CODE_GROUP_BY},
            h.current_vulnerability_band
        """,
    ),
]


# The 0010 definitions verbatim, so the reverse is a true reverse.
BACKWARD: list[tuple[str, str]] = [
    (
        "mv_explorer_household_by_subcounty_demographics",
        f"""
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
        {_HEAD_SEX.strip()}
        {_HEAD_AGE_BAND.strip()}
        WHERE h.is_deleted = FALSE
        GROUP BY
            h.sub_region_id, h.district_id, h.sub_county_id,
            head_sex.code, head_age_band.band
        """,
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
    ),
]


def _rebuild(schema_editor, pairs):
    """Drop and recreate each matview, then populate it.

    Populated immediately rather than left WITH NO DATA: an unpopulated
    matview raises on any SELECT, which the aggregate endpoint turns
    into a 503. Leaving the window open between `migrate` and the 01:00
    beat run would read as an outage. Same reasoning as 0011.
    """
    with schema_editor.connection.cursor() as cur:
        for name, definition in pairs:
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name};")
            cur.execute(
                f"CREATE MATERIALIZED VIEW {name} AS {definition} WITH NO DATA;",
            )
            # REFRESH ... CONCURRENTLY needs this; the beat task uses it.
            cur.execute(f"CREATE UNIQUE INDEX {name}_pk ON {name} (id);")
            cur.execute(f"REFRESH MATERIALIZED VIEW {name};")


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        # SQLite shadow tables carry plain VARCHAR columns — nothing to
        # change there; only the values the Postgres DDL computes differ.
        return
    _rebuild(schema_editor, FORWARD)


def backward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _rebuild(schema_editor, BACKWARD)


class Migration(migrations.Migration):
    dependencies = [
        ("data_management", "0011_household_shocks_matview"),
        # The matviews read geographicunit.code, so they must be built
        # after that column reaches its final width — see the docstring.
        ("reference_data", "0017_alter_geographicunit_code"),
    ]
    operations = [migrations.RunPython(forward, backward)]
