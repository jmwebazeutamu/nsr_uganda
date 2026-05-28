"""apps.data_explorer (DATA-EXP) — discovery + aggregate-preview surface.

Read ADR-0023 (docs/adr/0023-data-explorer.md) before changing anything
here. The module is read-only, k-anonymity-enforced, geographic-floor
limited to sub-county, and hands off to apps.data_requests for record-
level extracts. No raw SQL. No writes against DAT.
"""

default_app_config = "apps.data_explorer.apps.DataExplorerConfig"
