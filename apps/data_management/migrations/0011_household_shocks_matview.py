"""The household_shocks Data Explorer matview.

The dataset has been declared since US-DATA-EXP-001 — in
matview_models.HouseholdShocksSubregion, in the privacy-class seeds, and
in the refresh list, which is existence-aware precisely so a matview
joins in once its DDL lands. The DDL never landed, so the dataset
resolved to a table that does not exist.

That was invisible while it would have been empty anyway. It stops being
invisible now that section K shock detail reaches the registry: the
first household with a Shock row makes this the difference between a
dataset that reads zero and one that errors.

## sub_region_code holds a CODE here, not a foreign key

The two matviews built in 0010 put `h.sub_region_id::text` into a column
named `sub_region_code` — the GeographicUnit primary key, "13545", not
"SR-WEST-NILE-NORTHERN". Everything that consumes that column expects a
code:

  * ABAC matches ScopeLevel.SUB_REGION against `sub_region_code`
    (_SUB_REGION_DENORM in apps/security/abac.py), and OperatorScope
    rows carry codes — "411.05.05.04", not a row id.
  * data_explorer.query_builder filters the same column against the
    codes a caller supplies.
  * Household.sub_region_code and Shock.sub_region_code, the denormalised
    columns this is a projection of, both hold the code.

So this matview stores the code. That leaves it inconsistent with its
two siblings, which is the lesser of the two evils: a new matview
written to match a convention that cannot be scoped is a second broken
dataset rather than one. The two existing ones are recorded as a
finding; fixing them changes live aggregates and belongs with whoever
owns that dataset.

## Counting

A household can hold several Shock rows — section K asks K03/K04 once
per livelihood, so one household can report up to four different shocks.
`household_count` therefore counts DISTINCT households, not rows.
"""

from django.db import migrations

NAME = "mv_explorer_household_shocks_subregion"

DEFINITION = """
    SELECT
        md5(
            COALESCE(h.sub_region_code, '')
            || '|' || COALESCE(s.shock_type, '')
            || '|' || COALESCE(s.severity, '')
        ) AS id,
        now() AS refreshed_at,
        COALESCE(h.sub_region_code, '') AS sub_region_code,
        COALESCE(s.shock_type, '') AS shock_type,
        COALESCE(s.severity, '') AS severity,
        COUNT(DISTINCT s.household_id) AS household_count
    FROM data_management_shock s
    JOIN data_management_household h
        ON h.id = s.household_id
        AND h.is_deleted = FALSE
    WHERE s.is_deleted = FALSE
    GROUP BY h.sub_region_code, s.shock_type, s.severity
"""


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        # SQLite (tests) has no materialised views; matview_models are
        # managed=False and the refresh helper is vendor-guarded.
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS {NAME} AS {DEFINITION} "
            f"WITH NO DATA;",
        )
        # REFRESH ... CONCURRENTLY requires a unique index, and the
        # nightly refresh uses it so the dataset never serves a half-built
        # table.
        cur.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {NAME}_pk ON {NAME} (id);",
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {NAME}_sub_region "
            f"ON {NAME} (sub_region_code);",
        )
        # Populate now rather than waiting for 01:00: a matview created
        # WITH NO DATA raises on read, and the aggregate endpoint turns
        # that into a 503 that reads as an outage rather than an empty
        # dataset.
        #
        # The same hole exists for the 0010 pair, which have shipped
        # unpopulated since they were built and are only readable because
        # beat has since run. Rather than leave two conventions, this
        # closes it for every Data Explorer matview: after `migrate`,
        # every one of them is readable. The query is self-contained (no
        # import of EXPLORER_MATVIEWS — migrations must not track app
        # code) and idempotent: on an established database the others are
        # already populated and are skipped.
        cur.execute(
            r"SELECT matviewname FROM pg_matviews "
            r"WHERE matviewname LIKE 'mv\_explorer\_%' "
            r"AND ispopulated = false;",
        )
        for (matview,) in cur.fetchall():
            cur.execute(f"REFRESH MATERIALIZED VIEW {matview};")


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {NAME};")


class Migration(migrations.Migration):
    dependencies = [("data_management", "0010_data_explorer_matviews")]
    operations = [migrations.RunPython(create, drop)]
