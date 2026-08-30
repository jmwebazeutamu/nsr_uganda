# /design — NSR MIS Design Handoff

This folder holds the design source-of-truth for the NSR MIS operator console and CAPI tablet UI.

## Layout

```
/design
├── README.md                   # this file
├── v0.1/
│   ├── tokens.css              # design tokens (colours, type, spacing, shape) — imported everywhere
│   ├── components.md           # component library contract for the dev team
│   ├── acceptance.md           # screen → user story map + per-screen acceptance gates
│   └── screens/                # HTML mockups exported from Claude Design
│       ├── 01_capture_desktop.html
│       ├── 01_capture_capi.html
│       ├── 02_receipt_slip.html
│       ├── 02_receipt_sms.html
│       ├── 03_dih_review_queue.html
│       ├── 04_connector_runs.html
│       ├── 05_dedup_compare.html
│       ├── 06_upd_reviewer.html
│       ├── 07_drs_query_builder.html
│       ├── 07_drs_field_selector.html
│       ├── 07_drs_preview.html
│       ├── 07_drs_delivery.html
│       ├── 08_dpo_console.html
│       ├── 09_household_detail.html
│       └── 10_home_<role>.html
└── mockups/                    # legacy / scratch mockups (not source-of-truth)
```

## Source documents

- The brief that generated this folder: `/docs/04_ui_design_brief.md`.
- The SAD section that the screens must conform to: `/docs/01_solution_architecture.docx` §4 and §11.
- The user stories anchored to each screen: `/docs/03_backlog.xlsx`.

## How to add a new screen

1. Pick a user story from the backlog. Confirm the priority is Must or Should.
2. Add a row to `v0.1/acceptance.md` mapping the screen to the user story.
3. Build the mockup in Claude Design using the relevant Section-12 prompt from the brief.
4. Export as standalone HTML to `v0.1/screens/`.
5. Lint the HTML against `tokens.css`: every colour, font, or spacing value must reference a CSS variable, not a hardcoded hex.
6. Open the screen at 1366 wide and run the per-screen acceptance gates.
7. Commit with message `design(<screen>): add per Section <N>`.

## How to revise an existing screen

1. Bump the design version: copy `v0.1/` to `v0.2/` and revise there. Keep `v0.1/` immutable for the engineering team that built against it.
2. Document the diff in `v0.2/CHANGELOG.md`.
3. Update `/CLAUDE.md` to point to the new version.

## What this folder is NOT

- It is not a working frontend. The engineering team builds Vue or React components that match this contract.
- It is not the final implementation pixel-by-pixel. Engineering may make small adjustments to fit the framework idiom, but tokens, status vocabulary, and acceptance gates are binding.
- It is not a place for marketing pages, hero illustrations, or anything not anchored to a user story.

## Version

0.1 — 14 May 2026. Owner: NSR MIS Architecture Team.
