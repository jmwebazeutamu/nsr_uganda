# Architecture Decision Records

The full text of each ADR lives at `/docs/adr/`. This page is the index, with a one-line summary and the modules each ADR touches.

| ID | Title | Touches |
|---|---|---|
| ADR-0001 | Architecture style — modular monolith + DIH | All |
| ADR-0002 | Identifier strategy — ULIDs externally, encrypted NIN | DAT, SEC, IDV |
| ADR-0003 | Migration policy — reversible through Sprint 5; forward-only thereafter | All |
| ADR-0004 | CAPI form runtime — decision pending (DDUP-O-02) | INT, CAPI |
| ADR-0005 | Sub-region partitioning | DAT |
| ADR-0006 | Keycloak realm design | SEC, partners |
| ADR-0007 | Connector plugin pattern | DIH |
| ADR-0008 | Pagination and throttling | API |
| ADR-0009 | Admin and Console UI strategy | Admin Console |
| ADR-0009-dqa | DQA Rule Editor UI | DAT-DQA, Admin Console |
| ADR-0010 | Coded fields via ChoiceList | REF-DATA, DAT |
| ADR-0011 | Partners module | Partners, DRS, REF |
| ADR-0012 | DSA signature workflow | Partners |
| ADR-0013 | Canonical Partner and DSA models | Partners, DIH |
| ADR-0014 | Programme registration data model | Partners, REF |
| ADR-0015 | Consolidate referral programme into partners | REF, Partners |
| ADR-0016 | DSA scope edit and renewal | Partners, DRS |
| ADR-0017 | Detail entities as tables | DAT |
| ADR-0018 | Repeat groups as child tables | DAT, INT |
| ADR-0019 | Sensitive health encryption | DAT, SEC |
| ADR-0020 | FIES / FCS computed columns | DAT, PMT |

## When to write a new ADR

Per [contributing](../about/contributing.md), write an ADR when:

- You pick between technologies where the choice is not obvious from the stack lock (`Postgres vs Mongo`: no ADR. `RabbitMQ vs Redis Streams for X workload`: ADR).
- You commit to a contract that other modules will depend on (`This entity is canonically owned by app Y`).
- You override a default that came from the SAD.
- You close an open item from SAD §12.

Use the existing ADRs under `/docs/adr/` as templates.
