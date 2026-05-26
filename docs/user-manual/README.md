# NSR MIS — User Manual

Source for the NSR MIS user manual. Lives in the dev repo so a story merge can update the manual in the same PR.

## Build and serve

You need Python 3.12 and the repo's `.venv`.

```bash
# from /docs/user-manual
pip install mkdocs-material
mkdocs serve            # live preview at http://127.0.0.1:8001/
mkdocs build --strict   # full build, fails on broken links
```

Output goes to `docs/user-manual/site/` (already in `.gitignore`).

## Serve via Django at /manual/

The Django app has a `manual()` view in `nsr_mis/views.py` and a route at
`/manual/` (with a `<path:path>` catch-all) that serves the contents of
`docs/user-manual/site/`. Mirrors the same dev-convenience pattern as
`/console/`.

```bash
cd docs/user-manual && mkdocs build      # produces site/
cd ../.. && ./start-nsr-ug.sh            # serves /manual/
```

Then open `http://localhost:8000/manual/` in your browser.

Rebuild any time content changes; the view reads the latest files on
every request. Production deploys serve `site/` through nginx, not
Django.

## Structure

```
docs/user-manual/
├── mkdocs.yml          # nav and theme config
├── docs/               # the manual itself
│   ├── index.md
│   ├── about/          # how to read, glossary, changelog
│   ├── admin/          # System Administrator guide
│   ├── steward/        # Data Steward / DQA Officer guide
│   ├── field/          # Parish Chief / Field officer guide
│   ├── partner/        # MDA Partner / API consumer guide
│   ├── modules/        # one short page per functional module
│   └── appendices/     # ADRs, story map, status legend
└── README.md           # this file
```

## How to add a section when a story ships

1. Pick the audience guide and the right page.
2. Add a section anchored to the story ID, e.g. `## US-082 Violations dashboard`.
3. Update the status badge on the related `modules/<code>.md` page.
4. Record the change in `about/changelog.md`.
5. Link to the ADR if the story closed an open item.

See `docs/about/contributing.md` for the full rules.

## Status badges

Use these four labels. They map to colour in the rendered page.

- **Built and in use** — the feature works end-to-end against the spec.
- **Partial** — usable, but the page calls out what's missing.
- **Scaffolded** — wiring exists, no operator surface yet.
- **Planned** — not built. The page describes the intended behaviour and the sprint.

The legend lives at `appendices/status-legend.md`.
