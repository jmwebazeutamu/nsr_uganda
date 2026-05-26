# NSR MIS User Manual

Welcome. This is the user manual for the Uganda **National Social Registry MIS**, built for the Ministry of Gender, Labour and Social Development (MGLSD).

The Registry holds socio-economic data on households nationally. Target scale at full national load: 12 million households across 9 sub-regions.

## Who this manual is for

You are reading the right page if you are one of these people.

| You are a... | Start here |
|---|---|
| System administrator deploying or operating the platform | [System Administrator guide](admin/index.md) |
| Data Steward or DQA officer reviewing records, rules, and duplicates | [Data Steward guide](steward/index.md) |
| Parish Chief, CDO, or field officer capturing households | [Field officer guide](field/index.md) |
| MDA partner consuming data through the Data Request Service (DRS) | [MDA Partner guide](partner/index.md) |
| Developer or architect looking up a module | [Module reference](modules/index.md) |

## What state the system is in

Sessions S0 through S4 are complete. We have shipped the audit-bearing core: schema, DQA, DDUP tier 1 and 2, the DIH framework with 8 connector classes, partner and DSA models, the DRS Query Builder and Field Selector, and the Reporting dashboard pack. Six modules have partner-side ABAC plus full audit chains.

The CAPI offline path, questionnaire authoring (US-116 to US-120), full DRS delivery slices (US-099 to US-104), and Single Registry beneficiary exchange (US-058 to US-062) are not yet built. Each unbuilt page carries a **Planned** badge with the target sprint.

For a one-page snapshot of every module, see the [Module reference index](modules/index.md). For the live status of every story, see `/docs/08_sprint_plan.xlsx`.

## How this manual is maintained

The manual lives in the same repo as the code. When a story ships, the engineer who closed it updates the relevant page in the same merge request. See [Contributing](about/contributing.md) for the rules.

The current version of this manual is **v0.1** (25 May 2026). See the [Changelog](about/changelog.md) for what changed.

## How to access

| Where | URL |
|---|---|
| Dev server (Django serves the built site) | `http://localhost:8000/manual/` |
| Local live preview while editing | `mkdocs serve` from `docs/user-manual/` |
| Production | nginx serves `docs/user-manual/site/` (Planned) |

## Conventions

- Times are stored in UTC and rendered in **East Africa Time (UTC+3)**.
- Measurements use the **metric system**.
- Money is in **Uganda Shillings (UGX)** unless stated.
- Identifiers shown as `01HXYZ...` are **ULIDs** (per [ADR-0002](appendices/adrs.md)).
- Every page carries a status badge near the top. The badges are defined in the [Status legend](appendices/status-legend.md).

## Quick links

- [Glossary](about/glossary.md) — acronyms and Uganda-specific terms.
- [Architecture Decision Records](appendices/adrs.md) — the 20 ADRs that pin down architecture choices.
- [Story-to-page map](appendices/story-map.md) — which user story is documented where.
- **Solution Architecture Document** — the master spec at `/docs/01_solution_architecture.docx` (open from the repo, not from this site).
