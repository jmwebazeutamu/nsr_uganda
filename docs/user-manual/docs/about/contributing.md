# Contributing to this manual

The manual lives in the dev repo so a story merge can update the manual in the same pull request. If you add a feature, update the manual.

## Rules

1. **One PR, one feature, one doc update.** A story PR that touches user-visible behaviour must include a doc change in `/docs/user-manual/`. Reviewers will ask.
2. **Anchor every section to a story ID.** Use `## US-XXX Short title`. The story-to-page map ([appendices/story-map.md](../appendices/story-map.md)) is built from these anchors.
3. **Update the status badge.** If a module page goes from Scaffolded to Built, change the badge at the top of the module page.
4. **Note breaking API changes in `/docs/api_changelog.md`**, then link to that entry from the relevant page in this manual.
5. **Avoid restating the SAD.** Link to it instead. The SAD changes; copies go stale.
6. **No screenshots without alt text.** Screen readers matter. Use the `alt` attribute.
7. **Follow the writing style** below.

## Where to add a section

| Story type | Page to update |
|---|---|
| New admin task (loader, secret, observability target) | `admin/<topic>.md` |
| New steward workflow (rule, dashboard, review screen) | `steward/<topic>.md` |
| New field officer flow (capture, lookup, GRM) | `field/<topic>.md` |
| New partner-facing surface (DRS, portal, API endpoint) | `partner/<topic>.md` |
| Module gains a new entity or endpoint | `modules/<code>.md` |
| Architectural decision | `appendices/adrs.md` plus the ADR file itself under `/docs/adr/` |

## Page template

```markdown
# Page title

!!! info "Status"
    **Built and in use** — last verified 25 May 2026

One sentence saying what this page covers.

## What it does

Two or three sentences. Active voice. No marketing.

## US-XXX First slice

Walkthrough. Code blocks for commands. Tables for fields.

## Where to find it in the system

| Surface | Path |
|---|---|
| URL | `/api/v1/<module>/...` |
| Screen | `/design/v0.1/screens/screens-<name>.jsx` → `<ComponentName>` |
| OpenAPI tag | `<module>` |

## Related

- ADR-XXXX
- Story US-XXX
```

## Writing style

Read the user preferences in `/CLAUDE.md` and follow them in the manual too. The shortlist:

- Direct, personable, casual. Not upbeat.
- Information-rich and concise. No waffle.
- Short sentences. Short paragraphs.
- Active voice. Address the reader as "you".
- Bullets and tables where they help.
- Metric system.
- No em dashes.
- Do not use the banned word list (see `/CLAUDE.md` user preferences block).

## Build and verify

```bash
cd docs/user-manual
mkdocs build --strict
```

`--strict` fails on broken internal links and undefined nav entries. Fix the warnings before you merge.
