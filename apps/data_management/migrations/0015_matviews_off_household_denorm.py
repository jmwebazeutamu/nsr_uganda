"""Rebuild the Data Explorer matviews off Household's own code columns.

Migration 0014 denormalised every UBOS code onto Household. These
matviews no longer need to join `reference_data_geographicunit` to
project them, which removes the reason 0012 and 0013 had to declare an
explicit dependency on `reference_data.0017`:

    cannot alter type of a column used by a view or rule
    DETAIL: rule _RETURN on materialized view
            mv_explorer_household_by_subcounty_demographics
            depends on column "code"

After this, the only tables these matviews read are
`data_management_household`, `data_management_member` and
`data_management_shock`. `geographicunit.code` can be altered again
without dropping anything.

The projected VALUES do not change — 0014's backfill reads the same
`geographicunit.code` the join did, and a contract test asserts the
mirror matches its FK for every household. What changes is where they
are read from, and therefore what these matviews depend on.

Four joins per household row also go away. At 12M households that is
the difference between a refresh that walks the geography table four
times and one that does not.

The reverse restores the 0013 definitions, joins and all.
"""

import importlib

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

# Straight off Household now. COALESCE stays: village_code is blank by
# design when the UBOS frame carries no village row for a parish.
_KEY = """
                COALESCE(h.region_code, '')
                || '|' || COALESCE(h.sub_region_code, '')
                || '|' || COALESCE(h.district_code, '')
                || '|' || COALESCE(h.county_code, '')
                || '|' || COALESCE(h.sub_county_code, '')
"""

_COLUMNS = """
            COALESCE(h.region_code, '') AS region_code,
            COALESCE(h.sub_region_code, '') AS sub_region_code,
            COALESCE(h.district_code, '') AS district_code,
            COALESCE(h.county_code, '') AS county_code,
            COALESCE(h.sub_county_code, '') AS sub_county_code,
"""

_GROUP_BY = (
    "h.region_code, h.sub_region_code, h.district_code, "
    "h.county_code, h.sub_county_code"
)

SHOCKS = "mv_explorer_household_shocks_subregion"

FORWARD: list[tuple[str, str]] = [
    (
        "mv_explorer_household_by_subcounty_demographics",
        f"""
        SELECT
            md5(
                {_KEY.strip()}
                || '|' || COALESCE(head_sex.code, '')
                || '|' || COALESCE(head_age_band.band, '')
            ) AS id,
            now() AS refreshed_at,
            {_COLUMNS.strip()}
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
            {_GROUP_BY},
            head_sex.code, head_age_band.band
        """,
    ),
    (
        "mv_explorer_household_by_subcounty_pmt",
        f"""
        SELECT
            md5(
                {_KEY.strip()}
                || '|' || COALESCE(h.current_vulnerability_band, '')
            ) AS id,
            now() AS refreshed_at,
            {_COLUMNS.strip()}
            COALESCE(h.current_vulnerability_band, '') AS pmt_band,
            COUNT(DISTINCT h.id) AS household_count
        FROM data_management_household h
        WHERE h.is_deleted = FALSE
        GROUP BY
            {_GROUP_BY},
            h.current_vulnerability_band
        """,
    ),
    (
        SHOCKS,
        """
        SELECT
            md5(
                COALESCE(h.region_code, '')
                || '|' || COALESCE(h.sub_region_code, '')
                || '|' || COALESCE(s.shock_type, '')
                || '|' || COALESCE(s.severity, '')
            ) AS id,
            now() AS refreshed_at,
            COALESCE(h.region_code, '') AS region_code,
            COALESCE(h.sub_region_code, '') AS sub_region_code,
            COALESCE(s.shock_type, '') AS shock_type,
            COALESCE(s.severity, '') AS severity,
            COUNT(DISTINCT s.household_id) AS household_count
        FROM data_management_shock s
        JOIN data_management_household h
            ON h.id = s.household_id
            AND h.is_deleted = FALSE
        WHERE s.is_deleted = FALSE
        GROUP BY h.region_code, h.sub_region_code, s.shock_type, s.severity
        """,
    ),
]


def _rebuild(schema_editor, pairs):
    with schema_editor.connection.cursor() as cur:
        for name, definition in pairs:
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name};")
            cur.execute(
                f"CREATE MATERIALIZED VIEW {name} AS {definition} WITH NO DATA;",
            )
            cur.execute(f"CREATE UNIQUE INDEX {name}_pk ON {name} (id);")
            # Populated here, not at 01:00 — an unpopulated matview
            # raises on read and the endpoint turns that into a 503.
            cur.execute(f"REFRESH MATERIALIZED VIEW {name};")


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _rebuild(schema_editor, FORWARD)


def backward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    prior = importlib.import_module(
        "apps.data_management.migrations.0013_matview_full_geo_ladder",
    )
    _rebuild(schema_editor, prior.FORWARD)


class Migration(migrations.Migration):
    # No reference_data dependency any more — that is the point.
    dependencies = [("data_management", "0014_household_geography_codes")]
    operations = [migrations.RunPython(forward, backward)]
