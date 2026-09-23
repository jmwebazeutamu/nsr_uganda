"""Carry the whole geographic ladder, not three rungs of it.

Migration 0012 fixed the three geographic columns to hold codes. It did
not ask whether three columns were the right three.

The UBOS frame is region → sub_region → district → **county** →
sub_county → parish → village. `Household` carries every one as an FK.
`ScopeLevel` declares every one. `abac._LEVEL_FIELD` maps every one. But
the matviews carried sub_region, district and sub_county, and
`query_builder.field_map` listed exactly those three — so a request
scoped to a county (above the sub-county floor, and therefore accepted
by the validator) found no column and **fell through to unfiltered**:

    county   102.2          -> 322 rows, 354 households   (all of Uganda)
    region   R-CENTRAL      -> 322 rows, 354 households
    county   TOTAL-NONSENSE -> 322 rows, 354 households

A national answer wearing a county label, with the k-anonymity
suppression computed against the national population instead of the
county's, and a nonsense code returning it too.

This adds `region_code` and `county_code` to the two household
matviews, and `region_code` to the shocks matview, so every dataset can
be filtered at every level from national down to its own
`geographic_floor`. The fail-open branch in `_apply_geographic_scope`
is gone in the same change; `apps/data_explorer/geography.py` now
derives the ladder once, from `ScopeLevel`.

## Grain is unchanged

county and region are functionally determined by sub_county, so adding
them to the GROUP BY cannot split a row — verified on production before
writing this: across 297 (sub_region, district, sub_county)
combinations, **zero** map to more than one county or more than one
region, and no household has a null county or region FK.

## Same ALTER-column coupling as 0012

These matviews read `reference_data_geographicunit.code`, so they must
be built after `reference_data.0017` widens it and any future migration
altering that column has to drop them first. Denormalising the codes
onto Household is still the durable fix.
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

# One GeographicUnit row per FK — each names a specific versioned row,
# so none of these can fan out.
_GEO_JOINS = """
        LEFT JOIN reference_data_geographicunit r  ON r.id  = h.region_id
        LEFT JOIN reference_data_geographicunit d  ON d.id  = h.district_id
        LEFT JOIN reference_data_geographicunit cy ON cy.id = h.county_id
        LEFT JOIN reference_data_geographicunit sc ON sc.id = h.sub_county_id
"""

_KEY = """
                COALESCE(r.code, '')
                || '|' || COALESCE(h.sub_region_code, '')
                || '|' || COALESCE(d.code, '')
                || '|' || COALESCE(cy.code, '')
                || '|' || COALESCE(sc.code, '')
"""

_COLUMNS = """
            COALESCE(r.code, '') AS region_code,
            COALESCE(h.sub_region_code, '') AS sub_region_code,
            COALESCE(d.code, '') AS district_code,
            COALESCE(cy.code, '') AS county_code,
            COALESCE(sc.code, '') AS sub_county_code,
"""

_GROUP_BY = "r.code, h.sub_region_code, d.code, cy.code, sc.code"

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
        {_GEO_JOINS.strip()}
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
        {_GEO_JOINS.strip()}
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
                COALESCE(r.code, '')
                || '|' || COALESCE(h.sub_region_code, '')
                || '|' || COALESCE(s.shock_type, '')
                || '|' || COALESCE(s.severity, '')
            ) AS id,
            now() AS refreshed_at,
            COALESCE(r.code, '') AS region_code,
            COALESCE(h.sub_region_code, '') AS sub_region_code,
            COALESCE(s.shock_type, '') AS shock_type,
            COALESCE(s.severity, '') AS severity,
            COUNT(DISTINCT s.household_id) AS household_count
        FROM data_management_shock s
        JOIN data_management_household h
            ON h.id = s.household_id
            AND h.is_deleted = FALSE
        LEFT JOIN reference_data_geographicunit r ON r.id = h.region_id
        WHERE s.is_deleted = FALSE
        GROUP BY r.code, h.sub_region_code, s.shock_type, s.severity
        """,
    ),
]

# New columns for the non-Postgres shadow tables built in 0010.
#
# Every shadow gets `region_code`, because `region_code` lands on
# _MatviewBase alongside `sub_region_code` — the invariant is that every
# matview carries both, and the five whose Postgres DDL is still backlog
# must project them when they are built. Every shadow that already
# carries district and sub-county gets `county_code` for the same
# reason: a matview with those two but no county is exactly the hole
# this migration closes.
_SUBCOUNTY_GRAIN = (
    "mv_explorer_household_by_subcounty_demographics",
    "mv_explorer_household_by_subcounty_pmt",
    "mv_explorer_member_by_subcounty_education",
    "mv_explorer_member_by_subcounty_employment",
    "mv_explorer_referrals_subcounty",
    "mv_explorer_grievances_subcounty",
)
_SUB_REGION_GRAIN = (SHOCKS, "mv_explorer_health_chronic_subregion")

_SHADOW_COLUMNS: list[tuple[str, tuple[str, ...]]] = (
    [(t, ("region_code", "county_code")) for t in _SUBCOUNTY_GRAIN]
    + [(t, ("region_code",)) for t in _SUB_REGION_GRAIN]
)


def _rebuild(schema_editor, pairs):
    with schema_editor.connection.cursor() as cur:
        for name, definition in pairs:
            cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name};")
            cur.execute(
                f"CREATE MATERIALIZED VIEW {name} AS {definition} WITH NO DATA;",
            )
            cur.execute(f"CREATE UNIQUE INDEX {name}_pk ON {name} (id);")
            # Populated here rather than at 01:00 — an unpopulated
            # matview raises on read and the endpoint turns that into a
            # 503. Same reasoning as 0011 and 0012.
            cur.execute(f"REFRESH MATERIALIZED VIEW {name};")


def _shadow(schema_editor, *, add: bool):
    with schema_editor.connection.cursor() as cur:
        for table, columns in _SHADOW_COLUMNS:
            for column in columns:
                if add:
                    cur.execute(
                        f'ALTER TABLE "{table}" '
                        f'ADD COLUMN "{column}" VARCHAR(48) DEFAULT \'\';',
                    )
                else:
                    cur.execute(
                        f'ALTER TABLE "{table}" DROP COLUMN "{column}";',
                    )


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        _shadow(schema_editor, add=True)
        return
    _rebuild(schema_editor, FORWARD)


def backward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        _shadow(schema_editor, add=False)
        return
    # Reverse to the 0012 shape — codes, but only three rungs. The
    # module name starts with a digit, so it cannot be imported by
    # name.
    import importlib

    prior = importlib.import_module(
        "apps.data_management.migrations.0012_matview_geography_codes",
    )
    _rebuild(schema_editor, prior.FORWARD)


class Migration(migrations.Migration):
    dependencies = [
        ("data_management", "0012_matview_geography_codes"),
        ("reference_data", "0017_alter_geographicunit_code"),
    ]
    operations = [migrations.RunPython(forward, backward)]
