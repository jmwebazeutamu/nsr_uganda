# DPIA — Multi-level ABAC scope enforcement (Impact Recording)

**Status**: For DPO review.
**Last updated**: 2026-06-19.
**Covers**: ABAC Phase 1 (full geographic granularity) + Phase 2 (close 9 personal-data coverage gaps). See ADR-0026.
**Parent document**: `/docs/dpia.md` (initial DPIA, 2026-05-14).

---

## Processing activity

Tightens the access-control boundary on personal data. No new data is collected, derived, retained, or shared; this is a **risk-reducing** change that narrows who can read/write existing records.

## Personal-data categories touched

Household and Member identifying + socio-economic data, consent records and withdrawal tickets, DQA evaluation outcomes, deduplication merge decisions, and current-value field reads — all **read/write access scope only**, no change to the data itself.

## DPIA impact

### Before

- ABAC enforced only `national` + `sub_region` scope. Operators scoped at `region` / `district` / `sub_county` / `parish` / `village` were silently fail-closed to zero rows — a least-privilege role (District M&E, Parish Chief) could not see its legitimate area, pushing operations toward over-broad `national` grants. That is the opposite of data minimisation: it incentivised wider access than the role needs.
- Nine personal-data endpoints (consent member matrix/history/capture/withdraw + DPO queue, DQA evaluation history + persist, DDUP merge decisions, UPD current-values) applied **no** geographic scope at all — any authenticated operator could read/write any household's records nationwide. This is the §8.6 "insider data exfiltration" threat materialised at the endpoint level.

### After

- Every `OperatorScope` level is enforced at every read; a scope grants exactly its geography (with automatic containment of finer units). Least-privilege roles can be granted their true area instead of `national`, restoring data minimisation.
- The nine gaps are closed: out-of-scope reads return 404 / empty, out-of-scope writes return 404. The DPO withdrawal queue is scoped (national DPO sees all; a regional reviewer sees only their area).
- Audit (§8.4) is unaffected — the scope filters layer *after* the audit-read emit, so every attempted read is still logged before the queryset is trimmed.

### Residual / deferred

- **Reporting aggregates** remain `sub_region`-coarse (aggregated, non-row-level). Upgrading to multi-level is a low-risk follow-up (ADR-0026 D4).
- **Citizen self-service** consent access is the operator path today; a data subject acting on their own consent will authenticate via the deferred Keycloak citizen realm and carry a separate self-access rule. Until then, only scoped operators reach those endpoints.
- **Grievance** visibility stays role-based (Django Group) by the documented GRM decision, not geography — unchanged here.

## Net effect

Risk-reducing. Narrows the insider-exfiltration surface (§8.6) and restores data minimisation for least-privilege roles. No new processing, retention, or sharing. Recommended for DPO acknowledgement and inclusion in the next privacy-risk-register review.
