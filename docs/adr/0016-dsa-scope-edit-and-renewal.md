# ADR-0016 — DSA scope-edit and renewal lifecycle

**Status**: Proposed
**Date**: 2026-05-20
**Authors**: NSR Unit engineering
**Sprint**: 27
**Stories**: US-S27-001 (this ADR), US-S27-002 … US-S27-007
**Parent ADRs**: ADR-0011 (partners module), ADR-0012 (DSA signature
workflow), ADR-0013 (canonical Partner + DSA), ADR-0014 (programme
registration), ADR-0015 (referral.Programme consolidation)

## Context

By the end of Sprint 26 the registry has a complete DSA **model**
(`apps.partners.DataSharingAgreement`) and **API**
(`/api/v1/dsas/`), plus an embedded sign-off workflow per ADR-0012.
What it does not have is a path for editing a DSA's scope after
activation, nor a renewal flow. Operationally three gaps surface:

1. **Active-DSA scope edits.** A partner expands its programme into
   a new sub-region; the DSA's `geographic_scope` M2M must grow
   to match. Today the only way to PATCH a DSA is via DRF — there
   is no UI, no version bump, and no required re-signature.
   That conflicts with DPPA 2019's expectation that an executed
   data-sharing agreement is immutable post-signature; any
   material change is a new legal instrument.

2. **Renewal.** Every DSA carries `effective_from` / `effective_to`;
   when the latter approaches, the partner needs a new DSA covering
   the next period. There's no clone-to-v+1 flow.

3. **Sequencing during renewal overlap.** Sprint 24's enforcement
   (`apps.data_requests.services.validate_against_dsa`) filters by
   `status="active"` on a single DSA per partner-programme join.
   If v(N) and v(N+1) are both `active` during the overlap window,
   the partner sees their `monthly_row_budget` doubled. We need
   an explicit supersession rule.

`apps.referral.Programme` consolidation closed in Sprint 26
introduced `Programme.dsa` as an FK pointer for the registration
wizard's single-DSA picker. That FK also needs a re-point rule on
renewal so programmes don't hold stale references to v(N).

## Decisions

### Decision 1 — Scope edits to a draft DSA: in-place PATCH

A `status="draft"` DSA hasn't been signed yet; its scope is still
under negotiation. PATCH `/api/v1/dsas/{id}/` updates
`field_scope`, `geographic_scope`, `monthly_row_budget`,
`entities_scope`, `sensitive_data_handling`, etc. in place. No
version bump, no signature requirement. Emits a single
`dsa_scope_changed` AuditEvent recording the diff in
`field_changes`.

### Decision 2 — Scope edits to an active DSA: forced version bump + new sign-off chain

An `active` DSA is a signed legal instrument. The scope-edit
action POSTs `/api/v1/dsas/{id}/edit-scope/` which:

1. Clones v(N) → v(N+1) draft (same code path as the renewal flow
   in Decision 4) inheriting the current scope.
2. Applies the requested scope changes to v(N+1).
3. Leaves v(N) untouched at `status="active"`.
4. Returns the new v(N+1) draft so the caller can submit it for
   sign-off via the existing ADR-0012 chain.

The motivation is DPPA 2019: scope is part of the executed
agreement. Any change creates a new instrument that needs the
same three signatures. The UI surface for this lands in
US-S27-002 — when the operator opens the scope-edit modal on an
active DSA, the modal makes the version-bump explicit ("This will
create v(N+1) and require fresh sign-off from the three roles
above").

Narrowing-only changes (e.g. dropping a sub-region, lowering
budget) follow the same path — symmetry of audit trail beats
optimisation. The DPO is step 3 of the existing sign-off chain
and is the right safeguard against over-broad changes.

### Decision 3 — Renewal: explicit endpoint, cloned scope, sequential supersession

`POST /api/v1/dsas/{id}/renew/` clones the source DSA into a
v(N+1) draft. Specifically:

- New `id` (ULID), `status="draft"`, `version = source.version + 1`
- Same `partner` FK, same `reference` (the reference is a stable
  partner-side identifier across versions; the version differs).
  Per ADR-0011 the existing `UniqueConstraint(reference, version)`
  permits this.
- `programmes` M2M copied verbatim.
- `geographic_scope` M2M copied verbatim.
- `field_scope`, `entities_scope`, `monthly_row_budget`,
  `sensitive_data_handling`, `retention_days`, `breach_sla_hours`,
  `classification`, `dpia_document_ref` copied.
- `effective_from` / `effective_to` left NULL — the partner sets
  them on the new draft (typically `effective_from = old.effective_to + 1d`).
- `signed_at` reset to NULL.
- New `DsaSignature` rows are NOT created; they're dispatched the
  usual way via `POST /api/v1/dsas/{id}/submit-for-signoff/`.

Emits one `dsa_renewed` AuditEvent with
`field_changes={"source_dsa_id": ..., "source_version": N,
"new_version": N+1}`.

### Decision 4 — Supersession: v(N) → renewed at v(N+1) activation

When v(N+1) reaches `status="active"` (i.e. all three signatures
recorded), `apps.partners.services.signature.record_signature`
gains a step:

1. Find any prior version of the same `reference` with
   `status="active"`.
2. Transition that prior version to `status="renewed"` (terminal).
3. Re-point `Programme.dsa` FK from v(N) → v(N+1) for every
   programme that pointed at v(N).
4. Emit `dsa_superseded` AuditEvent on v(N) with
   `field_changes={"superseded_by": v(N+1).id,
   "new_version": N+1, "programme_ids_repointed": [...]}`.

The DRS enforcement path
(`apps.data_requests.services.validate_against_dsa`) already keys
off `status="active"`, so v(N) drops out of validation
automatically when its status flips to `renewed`. No code change
needed in DRS for the budget-doubling avoidance.

`programmes` M2M on v(N) is left intact for historical audit;
queries that need "the DSA effective right now for programme X"
read `Programme.dsa` (the FK), which has been re-pointed.

### Decision 5 — Sensitive scope changes (e.g. `sensitive_data_handling: none → full`) follow Decision 2

No special-case workflow. The DPO is already the third signer on
the three-step chain (ADR-0012); that's the right safeguard. The
UI for US-S27-002 highlights sensitive changes in the diff
preview but doesn't gate them on a different role.

## API surface additions

| Method | Path                                   | Purpose |
|--------|----------------------------------------|---------|
| POST   | `/api/v1/dsas/{id}/edit-scope/`        | Scope-edit dispatch. Drafts: in-place PATCH. Active: clones to v+1 and returns the new draft. |
| POST   | `/api/v1/dsas/{id}/renew/`             | Clone v(N) → v(N+1) draft for the next effective window. |

Existing PATCH `/api/v1/dsas/{id}/` stays but is the lower-level
write surface — the scope-edit action is the safe orchestration
on top. PATCH on an `active` row is rejected at the serializer
level (returns 400 with a pointer to `/edit-scope/`).

## New audit-event actions

| Action | Fired on | `field_changes` keys |
|---|---|---|
| `dsa_scope_changed` | Successful in-place PATCH on a draft DSA, or successful scope application to a cloned v+1 | `before`, `after`, `version`, `editor` |
| `dsa_renewed` | Successful POST `/renew/` | `source_dsa_id`, `source_version`, `new_version` |
| `dsa_superseded` | A prior-version DSA transitioning to `renewed` because its successor activated | `superseded_by`, `new_version`, `programme_ids_repointed` |

## Status transition table after this ADR

```
draft → pending_signature → active
draft → draft  (scope edit in place)
active → active  (no state change on /edit-scope/; new v(N+1) draft is created instead)
active → renewing*  (when v(N+1) draft is pending_signature; optional indicator)
active → renewed    (terminal; when v(N+1) reaches active)
active → expiring   (effective_to within 30d; computed/derived, not assigned)
active → expired    (effective_to past)
active → suspended  (operator pause via /admin/)
```

*"renewing" is informational only — used by the dashboard to flag
that a renewal is in flight. The DSA stays `active` operationally
until supersession.

## Consequences

**Gains**

- Active DSAs cannot have their scope changed without going
  through the same three-signature chain that created them. The
  audit trail is symmetric.
- Renewal is a single explicit action with a documented data
  flow — no operator improvisation.
- Sprint 24's `validate_against_dsa` continues to work unchanged;
  budget-doubling during overlap windows is structurally
  impossible.

**Costs**

- One DSA can have many version rows in the table over its
  lifetime. Storage cost is negligible (a DSA row is a handful
  of fields + scope JSON), but the `/api/v1/dsas/` list grows
  monotonically. The default list view filters to current
  versions via `status NOT IN (renewed, expired, suspended)`.
- The "renewing" informational state needs UI surface in
  US-S27-004 (the cross-partner workbench) to avoid confusion
  ("why does this partner have two DSAs of the same reference?").
- Reading the M2M `programmes` on a `renewed` DSA returns the
  historical attachment, not the current one. Consumers that
  want "current programmes under this reference" should follow
  the `Programme.dsa` FK instead. Document in the API changelog.

## Migration policy

No schema changes. Forward-only — the new audit actions slot
into the existing `AuditEvent.action` column. The
`programme_dsa_repoint` step on activation is wrapped in a single
`@transaction.atomic` block so partial repointing on failure is
impossible.

## Open items

- **OI-S27-1**: Should renewal carry forward `effective_from` /
  `effective_to` as `effective_from = old.effective_to + 1d,
  effective_to = old.effective_to + 365d` by default, or leave
  both NULL for the operator to fill? Recommend leaving NULL —
  the operator's intent at renewal time is what counts. UI
  surface in US-S27-005 pre-fills the suggestion but doesn't
  hardcode it.
- **OI-S27-2**: An operator who tries to renew a `renewed` DSA
  should be silently redirected to the latest active version
  rather than getting a confusing error. Defer to US-S27-005's
  implementation.
- **OI-S27-3**: Cross-partner workbench needs an aggregate
  endpoint `/api/v1/dsas/summary/` to feed its KPI strip without
  N+1 queries. Lands in US-S27-004.

## References

- ADR-0011 — Partners module
- ADR-0012 — DSA signature workflow
- ADR-0013 — Canonical Partner + DSA in apps/partners
- ADR-0014 — Programme registration data model
- ADR-0015 — Consolidate referral.Programme into apps/partners
- Uganda Data Protection and Privacy Act 2019 — §16 ("Each
  authorised processing activity shall be documented in writing
  by the data controller…")
