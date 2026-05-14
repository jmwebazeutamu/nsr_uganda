# ADR-0001: Architecture style — modular monolith for the registry, separate service for the Data Integration Hub

- **Status**: Accepted
- **Date**: 14 May 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: MGLSD NSR Unit Coordinator, NSR Project Manager, NSR MIS Systems Architect
- **References**: SAD v0.6 §3.3, §4.6, §6, §7

---

## Context

The NSR MIS serves the Ministry of Gender, Labour and Social Development (MGLSD) and partner MDAs across nine sub-regions of Uganda, with a target steady-state load of 12 million households. The system has three operational profiles that pull in opposite directions:

1. **A high-integrity registry**: versioned household and member records, audit-bearing merges, PMT recompute on every relevant change, DSA-scoped reads under DPPA 2019, 99.5% availability target, RTO 4 hours, RPO 15 minutes.
2. **A churn-heavy ingestion surface**: connectors to UBOS bulk, Kobo, WFP SCOPE, ODK forms from multiple agencies, partner programme MIS systems, NIRA vital events. New sources arrive on a different cadence from registry releases.
3. **A field-facing capture layer**: CAPI tablets, parish walk-in, sub-county web entry, USSD pre-registration. Offline capable, low-bandwidth, government-tone UX.

The team is forming. Procurement of NITA-U production tenancy is non-trivial. Operating a service mesh is not within the team's current operational maturity. The release cadence target is monthly to production with a hotfix path, not daily.

We need an architecture style that handles the integrity, the churn, and the field-facing capture without forcing the team into an operational pattern it cannot run reliably in year one.

## Decision

We adopt a **modular monolith for the NSR Registry, with a separately deployable Data Integration Hub (DIH)** as a service. The two apps communicate over a single internal promotion API. Shared services (DAT-DQA, DAT-DDUP, IDV) live in the registry codebase and are callable as libraries from the DIH.

Concretely:

- **The Registry** is one Django 5.x application split into bounded module apps under `/apps/`, one per module: `intake`, `data_management`, `dqa`, `ddup`, `identity_verification`, `update_workflow`, `pmt`, `referral`, `grievance`, `api_gateway`, `data_requests`, `security`, `reporting`, `reference_data`. Each app owns its tables. Cross-app calls go through internal Python APIs, not HTTP. Single transactional database (PostgreSQL 16).
- **The DIH** is a second Django application with its own database schema (separate logical database; physically can colocate on the same PostgreSQL cluster behind row-level security). It owns: `SourceSystem`, `DataProvisionAgreement`, `Connector`, `ConnectorRun`, `RawLanding` (per-source), `MappingRule`, `MappingRuleVersion`, `StageRecord`, `PromotionDecision`, `PromotionBatch`, `Quarantine`. Outbound to the registry uses one endpoint: `POST /internal/dih/promote`.
- **Shared services** (DAT-DQA rule engine, DAT-DDUP matcher, IDV NIRA client) live in the registry codebase and are exposed as importable Python packages plus an internal HTTP fallback. The DIH calls the library form when colocated, the HTTP form when deployed separately. One implementation, two callers.
- **Async integration** uses RabbitMQ with an event store. Internal modules publish events (`household.registered`, `pmt.score.changed`, `household.updated`, `merge.committed`) that other modules consume. The DIH publishes `connector.run.completed` and similar.
- **Perimeter** is Kong (API gateway) for auth introspection, rate limits, mTLS to NIRA and to partner programmes, request audit. Keycloak provides OIDC for operators and OAuth 2.0 client_credentials for partner systems.

## Consequences

### Positive

- **Single-process transactional integrity** within the registry. Merge, version-row creation, audit-chain write, PMT recompute, and event emission happen in one Django transaction. No distributed-transaction pain.
- **Independent release cadence** for the DIH. Adding a Kobo project or a WFP connector does not force a registry release. Source-system churn is contained.
- **Different SLA and security postures** can be operated and reasoned about separately. The DIH can run at 99% with batch tolerance; the registry runs at 99.5% with read-heavy load.
- **One rule engine** (DAT-DQA) and **one match model** (DAT-DDUP). No drift between staging and registry quality logic.
- **Clean module boundaries** inside the registry, with the option to extract a module into its own service later if traffic or release cadence forces it. Phase-2 extraction candidates are the API Gateway, PMT recompute, and the DAT-DDUP nightly sweep.
- **Operational simplicity** suitable for a forming team: two apps to deploy, two databases (or two schemas), one event bus, one identity provider, one gateway.
- **Audit-chain reconstructability** is straightforward because all registry writes happen in one process and one database.

### Negative / costs

- The registry monolith grows large. Mitigation: strict module boundaries enforced via package structure plus CI checks (no cross-app imports of internal modules; cross-app calls go through declared internal APIs). Architecture fitness functions checked in CI.
- A second app to deploy and operate (the DIH). Mitigation: it ships under the same CI/CD pipeline, same Helm chart shape, same observability stack.
- The shared service pattern (DAT-DQA, DAT-DDUP as libraries used by both apps) requires versioning discipline. Mitigation: rule packs and match models are versioned in REF-DATA; the active version is selected at call time.
- Some duplication of data-access patterns between staging and registry. Mitigation: keep the canonical NSR schema as the source of truth and generate the staging schema from it.
- Phase-2 extraction will require work later. Acknowledged; the cost is intentionally deferred.

### Risks accepted

- **Single-process failure mode for the registry**. If the registry monolith goes down, all modules go down together. Mitigation: HA at the pod level (three replicas minimum), DR at the site level, blue-green deploys with feature flags.
- **DIH-to-registry coupling**. If the promotion API contract breaks, ingestion stalls. Mitigation: contract tests in CI; versioned promotion endpoint with a 12-month deprecation window.
- **Sub-region partitioning** at the database level (PostgreSQL declarative partitioning by sub-region) makes cross-sub-region queries more expensive. Mitigation: read replicas with cross-sub-region access for analytics.

## Alternatives considered

### A. Pure microservices (one service per module)

**Rejected.** Twelve modules plus four sub-modules would mean sixteen services on day one. Distributed transactions across DAT, DDUP, PMT, and REF would push us toward saga patterns or two-phase commit, both of which are expensive at the merge and PMT-recompute paths. Service mesh operation requires capability we have not procured. Phase 1 cannot absorb that overhead.

### B. Pure single monolith (DIH inside the registry)

**Rejected.** Source-system connector churn would force registry releases for every new partner. Different SLA and security profiles get conflated. Raw partner data and canonical registry data sit in the same blast radius. The audit story becomes harder because pre-promotion records have a different lawful basis from post-promotion records and we want that boundary enforced by deployment, not by code convention.

### C. Event sourcing as the system of record

**Rejected.** The audit chain plus versioning tables (HouseholdVersion, MemberVersion) give us most of the benefit (full reconstruction, as-of queries) without the operational cost of running an event store as primary storage. We use RabbitMQ as an integration mechanism with an event store for replay, not as the source of truth.

### D. CQRS at module level

**Rejected for MVP.** Premature. Read traffic from operators is served from OpenSearch and a read-only replica. The DRS partner read path runs against the read-only replica with RLS. If DRS query volume forces it later, CQRS can be added per module without re-architecting.

### E. Serverless (AWS Lambda, GCP Cloud Functions, Knative)

**Rejected.** NITA-U does not currently operate a serverless platform at the trust level the DPPA 2019 requires. Re-evaluate in Phase 2 if NITA-U procurement of a serverless tier matures.

### F. openIMIS code reuse

**Rejected for code, accepted for capability mapping.** openIMIS's code base is Java/Liferay-heavy and would force a stack change away from the locked Python/Django target. We reuse the conceptual capability model (Intake, Data Management, Eligibility, Updates, Reporting, Interoperability, Security, UI, Inclusive Registration, GRM) and the Standardised Questionnaire Engine ideas, not the source code. See SAD §4.7.

### G. Two databases physically separate from day one

**Rejected for Phase 1.** Two logical databases under one PostgreSQL cluster suffice. Row-level security plus separate schemas give us the isolation we need without the operational cost of two clusters. Re-evaluate if write contention emerges or if NITA-U mandates physical separation.

## Compliance

This decision aligns with the constraints in SAD §2.3:

- Hosting in the NITA-U Government Data Centre with a secondary DR site.
- Target stack already declared: Python/Django for application services, PostgreSQL as the system of record.
- Identity centralised at NIRA; the NSR does not duplicate biometric matching.
- UBOS as the authoritative source for the administrative hierarchy.
- CAPI offline mode mandatory for field work; supported by INT plus DIH offline-tolerant connectors.

It also satisfies the DPPA 2019 controls in SAD §8: lawful basis, purpose limitation, data minimisation, accuracy, storage limitation, integrity and confidentiality, and accountability, with the DIH boundary giving us a clean point to attach the inbound lawful basis (DPA) and the registry boundary attaching the outbound lawful basis (DSA).

## How the team operates against this decision

- **No cross-app Python imports across module apps in the registry.** Modules expose internal APIs (a small set of declared functions). CI enforces import discipline via a linter rule.
- **No HTTP between registry modules.** Cross-module calls are in-process Python.
- **HTTP only between the registry and the DIH** (one direction: DIH calls `POST /internal/dih/promote` on the registry). All other DIH/registry interaction is via the event bus.
- **Shared services** are imported as libraries inside the registry and called over a small internal HTTP if the DIH runs in a separate cluster. The library form is the primary; HTTP is the fallback.
- **OpenAPI 3.1 is required** for every external module endpoint and for the promotion API. Contract tests run in CI on every PR.
- **Migrations are forward-only in production** from Sprint 5 onward; reversible before that. The reverse plan is attached to each release ticket.

## Triggers to revisit this decision

This ADR will be re-opened if any of the following materialise:

1. The registry monolith approaches 200,000 lines of code or 80 minutes of CI runtime, whichever comes first.
2. A single module's release cadence consistently outpaces the rest by more than 2x (signal that it should be extracted).
3. DRS partner-facing read traffic exceeds 1,000 requests per second sustained, justifying its own service.
4. Phase 2 introduces a new operational tenant (e.g., a second registry for a different population) that would benefit from a multi-tenant service tier.
5. NITA-U procures a serverless or managed-Kubernetes tier that materially changes the operational cost calculus.

## Status changes log

| Date | Change | Author |
|---|---|---|
| 14 May 2026 | Accepted | NSR MIS Architecture Team |

---

End of ADR-0001. Place this file at `/docs/adr/0001-architecture-style.md` in the NSR MIS repository.
