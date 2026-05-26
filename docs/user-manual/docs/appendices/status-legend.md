# Status legend

Every page and module page carries a status badge near the top. The badge tells you what state the feature is in.

## The four badges

### Built and in use

The feature works end-to-end. Tests cover it. You can use the page as a manual. The team uses this feature themselves and would notice a regression.

Promote a page to this badge when:

- The acceptance criteria of the underlying story are all green.
- A contract test covers the API surface.
- The audit event is emitted and validated.
- The screen (if any) has shipped in `/design/v0.1/screens/`.

### Partial

The feature is usable but the page explicitly calls out gaps. Use it with care.

A page is Partial when:

- A core slice works, e.g. ChangeRequest submit works but the reviewer UI is not done.
- A related sub-feature is documented as Planned within the same page.

The body of the page must list **what is missing** as a numbered list and a target sprint.

### Scaffolded

The model and URLs exist. There is no operator surface yet. You can read the API contract and the model, but you cannot drive the feature through the console.

A page is Scaffolded when:

- Django models exist.
- DRF router is mounted at the URL.
- No `views.py` or thin viewset only.
- No screen under `/design/v0.1/screens/` for this surface.

### Planned

Not built. The page describes the intended behaviour and the target sprint. Use the page as a forward-looking spec.

A page is Planned when:

- No model is present, OR
- The story is "Not started" in `/docs/08_sprint_plan.xlsx`.

## How a page moves between badges

1. **Scaffolded → Partial**: when the first slice of the operator surface ships.
2. **Partial → Built and in use**: when all the gaps the page calls out are closed.
3. **Built and in use → Partial** (rare): when a regression is shipped and a known gap reappears. Update the changelog.
4. **Planned → any**: when the first story for the feature lands.

## On every page

The badge is rendered with the `!!! info "Status"` block (Material for MkDocs admonition):

```markdown
!!! info "Status"
    **Built and in use** — last verified <date>
```

Include a brief verification date when a reviewer last checked. Six months without a verification date is a sign the page needs a re-read.
