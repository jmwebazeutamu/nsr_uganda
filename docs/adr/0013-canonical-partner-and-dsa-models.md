# ADR-0013: Partner + DataSharingAgreement live in apps/partners — DRS consumes

- **Status**: Proposed
- **Date**: 19 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Engineering Lead, Partner Affairs Lead
- **References**: ADR-0011 (Partners module); ADR-0012 (DSA signature workflow); US-S19 (DRS); US-S23 (Partners module); US-S24 (this sprint).

---

## Context

Two `DataSharingAgreement` (and two `Partner`) classes coexist on `main` after Sprint 23:

| Owner | File | Shape | Used by |
|---|---|---|---|
| Sprint 19 (DRS, pre-existing) | `apps/data_requests/models.py:56` | `allowed_scopes` JSONField, local `Partner` model, `valid_from`/`valid_to`, status enum | DRS submit/render/deliver pipeline (`validate_against_dsa`, `render_bundle`), DRS admin, DRS API |
| Sprint 23 (Partners, mine) | `apps/partners/models.py:188` | ULID PK, `entities_scope` + `field_scope` JSONFields, `geographic_scope` M2M to GeographicUnit at any level, `monthly_row_budget`, `sensitive_data_handling` code, retention/breach SLA, signature chain | Partner registration wizard, partner detail screen, partner-module admin, dashboards, breach detector, DSA-signature workflow per ADR-0012 |

The two registries do not overlap in data today — `apps/data_requests`'s Partner + DSA tables are empty in dev (and presumably staging); the seeded operational data lives in `apps/partners/`. But the *types* duplicate, the *enforcement code* lives on one side, and the *user-facing workflow* lives on the other. Continuing as-is means:

- A DSA signed through the wizard never reaches the DRS enforcement path.
- A DSA created via the DRS admin never has signatures or breach detection.
- Two parallel data shapes for the same concept — a DPIA red flag and an audit-chain dilution.

US-S24 reconciles the two registries before extending DSA enforcement.

## Decision

**`apps/partners/` is the canonical owner of `Partner` and `DataSharingAgreement`. `apps/data_requests/` consumes both.**

Concretely:

1. **One model per concept.** The `Partner` and `DataSharingAgreement` classes in `apps/data_requests/models.py` are removed. Every caller that imported them (DRS services, admin, API, serializers, builder schema, tests) rewires to import from `apps.partners.models`.

2. **`DataRequest.dsa` FK becomes a pointer to `apps.partners.DataSharingAgreement`.** A migration repoints the column; existing rows are mapped via a data migration that lifts any DRS-local DSA rows into the canonical table preserving `reference`, `valid_from` → `effective_from`, `valid_to` → `effective_to`, `partner.code`. The legacy `allowed_scopes` JSON is mapped onto the canonical fields:

    | Legacy key | Canonical destination |
    |---|---|
    | `allowed_scopes.fields` | `field_scope` (dict keyed by group, value=True) |
    | `allowed_scopes.sub_region_codes` | `geographic_scope` M2M — resolved by `GeographicUnit.code` lookup at the sub_region level |
    | `allowed_scopes.programme_codes` | recorded in `entities_scope.programmes_allowed` until a richer model lands |
    | `allowed_scopes.max_rows` | `monthly_row_budget` |

3. **DRS keeps owning enforcement.** `validate_against_dsa()` and `render_bundle()` stay in `apps/data_requests/` — they are the gates DRS exposes. They rewrite to read the canonical fields (`field_scope`, `entities_scope`, `geographic_scope` M2M, `monthly_row_budget`, `partner.status`). The partners module exposes the *contract*; DRS exposes the *enforcement*.

4. **New Partner-status gate.** Submit + deliver paths refuse when `partner.status == "suspended"`. They emit a `dsa_scope_violation` AuditEvent. `partner.status == "alert"` continues to be a soft signal (breach detector flips it; renewal workflow unflips it) and does not block submit; the dashboard renders the chip.

5. **Structured delivery event.** The `deliver` AuditEvent's `field_changes` payload grows to `{partner_code, partner_id, dsa_reference, rows_delivered, manifest_sha256}`. The Sprint 23 usage-rollup task in `apps/partners/tasks.py` stops parsing partner code out of the free-text `reason` and reads `field_changes.partner_code`.

6. **Budget gate.** `validate_against_dsa()` rejects submits whose `max_rows` would push the trailing-30d sum over `monthly_row_budget` for the partner. Provider-status partners with `monthly_row_budget = NULL` continue to be skipped (ADR-0011 decision 3).

7. **Geographic scope check.** `render_bundle()` filters households by walking the canonical `geographic_scope` M2M up the geo tree — a DSA scoped at `sub_region=KARAMOJA` permits any household whose `sub_region` is Karamoja regardless of district. A DSA scoped at `district=PADER` only permits Pader households.

8. **OperatorScope unchanged.** Sub-region ABAC scoping for operators still uses the existing `apps.security.OperatorScope` table. Partner-scoped users (per `PartnerScopedQuerysetMixin`) continue to see only their own partner's DataRequests; that filter is orthogonal to the DSA scope and stays as-is.

## Consequences

### Positive

- Single source of truth for the Partner + DSA shape. Adding a field to either is a one-place change.
- DSA signed through the wizard (ADR-0012's three-step chain) is the same DSA DRS enforces. Audit chain reconstructs the full contract → enforcement path from a single timeline.
- Breach detector + UsageBar already read the canonical model; now the rollup task reads structured `field_changes` instead of free-text — drift between the dashboard's view and the partner's actual usage closes.
- The partner-portal follow-up (US-S12-010) reuses the same model on both sides — no second translation layer.

### Negative

- DRS test suite has to be rewritten — every fixture that constructs a local Partner / DSA now constructs the canonical one. Mechanical change; bounded to `apps/data_requests/tests.py` and the integration tests.
- The legacy `allowed_scopes` JSON is lossier than the canonical shape — when we lift older rows, `programme_codes` lands in a `entities_scope.programmes_allowed` sub-key rather than a structured M2M. Existing DRS-side admin / API consumers reading `allowed_scopes` need a transitional shim or to switch to the canonical fields directly. The DRS-side `DataRequest.request_payload.fields` etc. is unaffected (it's the user's *request*, not the DSA's *grant*).
- Two migrations in apps/data_requests — one to lift rows, one to swap the FK + drop the dupes. Sequence matters; both are forward-only with the reverse plan in the release ticket (ADR-0003).

### Neutral

- DRS-side API endpoints continue to live under `/api/v1/drs/` and `/api/v1/dsas/` — same URLs, same shapes for consumers reading the response body. The internal model swap is invisible to external callers as long as they don't introspect the database directly.
- The Partner-module admin already registers `DataSharingAgreement` (US-S23-006). The DRS-module admin's DSA registration goes away in this sprint.

## Out of scope

- The partner-portal (US-S12-010) — still owned by a future sprint; benefits from this consolidation but doesn't drive it.
- Document vault (DRS-O-02) — DSA / DPIA PDF storage still lives behind the operational ticket; the FK on the canonical DSA carries the reference string for now.
- Replacing `allowed_scopes` admin views — the DRS-side admin loses its DSA register; the partners-module admin is the place to edit a DSA. Documented in the Sprint 24 API changelog.

## Migration policy

Per ADR-0003, post-Sprint-5 migrations are forward-only with the reverse plan documented in the release ticket. The two migrations this sprint produces:

1. **Data migration (US-S24-002)** — iterates `apps.data_requests.DataSharingAgreement` rows (empty today in dev/staging) and idempotently creates the canonical counterpart in `apps.partners.DataSharingAgreement`. Maps `allowed_scopes` → canonical fields. Skips rows whose `reference` already exists in the canonical table.
2. **Schema migration (US-S24-003)** — repoints `DataRequest.dsa` FK to the canonical model using the map built in step 1. Drops `apps.data_requests.{Partner, DataSharingAgreement, DsaStatus}`.

Reverse plan: if rollback is needed within the sprint window, the inverse data migration recreates the DRS-local rows from the canonical model using the same field mapping. The reverse script will land at `/scripts/reverse/us_s24_003.py` if rollback becomes operationally relevant. Pre-emptively writing it before any production deploy.

## Open items

- **OI-S24-1.** DSA versioning across the consolidation. Sprint 23 versions DSAs via `(reference, version)`; the legacy DRS-side model didn't carry a version. Migrated rows default to `version=1`. Documented; no remediation required because no production data is being lifted.
- **OI-S24-2.** Programme-code scope. The legacy `allowed_scopes.programme_codes` lands in `entities_scope.programmes_allowed` for now. Adding a structured M2M (DSA ↔ Programme) is a follow-up — convenient once the Programme CRUD endpoint lands (open from Sprint 23).

---

Signed off by:

- NSR Unit Coordinator: ____________________ Date: __________
- Data Protection Officer: ____________________ Date: __________
- Engineering Lead: ____________________ Date: __________
- Partner Affairs Lead: ____________________ Date: __________

End of ADR-0013.
