# ADR-0026: Multi-level ABAC geographic-scope enforcement

- **Status**: Proposed
- **Date**: 19 June 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Security Lead, Engineering Lead
- **References**: SAD §8.2 (authentication & authorisation — "Attribute-based scope enforced by parish/sub-county/district/region tag on the user account. ABAC policies evaluated at every read"), §8.4 (audit), §8.6 (threat model — insider data exfiltration); ADR-0005 (sub-region partitioning + denormalised `sub_region_code`); DPIA §8 (access control); `apps/security/abac.py`; `apps/security/test_abac.py`.

---

## Context

SAD §8.2 mandates attribute-based access control where an operator's geographic tag — **parish / sub-county / district / region** — bounds which household and member records they can read, and ABAC is "evaluated at every read." §8.6 names insider data exfiltration (an operator dumping records outside their area) as a primary threat, with ABAC geographic scope as the first mitigation.

The Sprint-2 implementation enforced only **two** of the seven `ScopeLevel` values: `national` (wildcard) and `sub_region` (the ADR-0005 denormalised partition key). The resolver `scope_q_for_field` silently dropped `region`, `district`, `sub_county`, `parish`, and `village` scopes — and because the mixins fail closed, an operator carrying *only* a district or parish scope matched **zero rows**. A District M&E officer or a Parish Chief — exactly the roles in the SAD §8.2 least-privilege catalogue — could see nothing. The finer levels were modelled on `OperatorScope` but never enforced.

Separately, an audit of all DRF views found **9 personal-data endpoints** that bypassed the scope mixins entirely (consent member matrix/history/capture/withdraw + DPO queue, DQA evaluation history + persist, DDUP merge decisions, UPD current-values), returning or writing records regardless of the operator's geography.

This work is a precondition for any production deployment holding real household PII.

## Decision

### D1. Enforce every geographic `ScopeLevel`, keyed off Household's denormalised FKs.

`Household` denormalises the full UBOS ladder as foreign keys (`region`, `sub_region`, `district`, `county`, `sub_county`, `parish`, `village`). A scope at level *L* with code *C* therefore resolves to a single column predicate — `Q(<L>__code=C)` — and **containment is automatic**: a district scope matches every household in that district across all its sub-counties / parishes / villages, with no hierarchy traversal. `sub_region` keeps using the ADR-0005 denormalised `sub_region_code` (indexed partition key); the other levels match through the level FK's `code`.

`scope_q_for_field(user, field)` derives a relation **prefix** from the existing `scope_field_path` ("" for Household-shaped rows, "household__" for Referral / ProgrammeEnrolment / PMTResult / Member) and applies it to every level column. Consequently **no viewset declaration changed** — the mixins and their `scope_field_path` values are untouched; they gained full granularity for free.

The ID-subquery mixins (Submission/StageRecord, MatchPair, ChangeRequest, and now MergeDecision via a `match_pair__` prefix) resolve through `_scoped_household_ids`, which is itself built on `scope_q_for_field`, so the multi-level semantics live in exactly one place.

### D2. `national` and superuser remain the wildcard; everything else fails closed.

Unchanged: anonymous, no-active-scope, and partner-only (non-geographic) users see zero rows; `national` scope and Django superusers see all. Pre-promotion rows whose household reference is a provisional id with no `Household` row yet stay national-only (DIH visibility), matching the existing `HouseholdIdScopedQuerysetMixin`. The single-entity helpers (`user_can_access_household` / `user_can_access_member`) short-circuit on `_is_wildcard` **before** the existence check so national/superuser can still act on those provisional ids.

### D3. Close the 9 read/write coverage gaps; leave GRM role-based.

Single-entity views gate with `user_can_access_household` / `user_can_access_member` (Http404 for out-of-scope — an out-of-scope id is indistinguishable from a non-existent one). List/queryset views filter through the resolver (out-of-scope → empty, "rows just don't appear"). The DQA sync (`persist=false`) path keeps no gate: it evaluates only the caller-supplied payload and reads no stored data.

Grievance (`GrievanceViewSet` / `GrievanceTaskViewSet`) deliberately keeps its **role-based** visibility (Django Group, not geography) per the documented GRM decision — a GRM officer's queue is assignment-driven, not area-driven. This ADR does not change that.

### D4. Reporting aggregates stay sub_region-coarse (for now).

The `_scoped_codes` helper (sub_region-only) is retained for the handful of reporting views that `GROUP BY sub_region_code`. Row-level personal-data enforcement is multi-level; the aggregate dashboards remain sub_region-granular. Upgrading the aggregates to multi-level is a follow-up (low risk — the data is already aggregated, not row-level PII).

### D5. Scope is the geographic axis only.

This ADR covers the §8.2 *geographic* attribute. Other attributes — purpose-of-use, consent state, data-sensitivity classification, partner affiliation — have their own enforcement paths (consent module / ADR-0024, `PartnerScopedQuerysetMixin`, Data Explorer privacy classes / ADR-0023) and are out of scope here.

## Consequences

- Operators scoped at district / sub-county / parish now see their area's households (previously: nothing). This is a behaviour change only for the previously-broken finer levels; national / sub_region / superuser / fail-closed paths are byte-for-byte unchanged, which the regression suite confirms.
- Finer-level predicates traverse a FK to `GeographicUnit` (`district__code` etc.) rather than the denormalised `sub_region_code`. At national scale this should ride the existing per-level indexes on Household; if profiling shows a hotspot, denormalising the finer codes onto Household (mirroring ADR-0005's `sub_region_code`) is the escalation path.
- ABAC enforcement now covers every personal-data read/write surface except the intentionally role-based GRM and the deliberately-coarse reporting aggregates (D4).
- Test users that exercise gated endpoints must now carry an `OperatorScope` (or be superuser); fixtures were updated to grant national scope where the caller is a national role.

## Status note

Proposed. To be ratified alongside the production-deployment ADR (single-VPS vs NITA-U k8s) before real PII lands in any environment.
