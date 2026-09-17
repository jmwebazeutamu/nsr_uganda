# Branching and release flow

**Version 1.0 — 17 September 2026.** Supersedes nothing; this is the first
written statement of the flow now that there are two deploy targets.

## The three environments

| Environment | Host | Compose file | Deployed by |
|---|---|---|---|
| **dev** | developer box / Multipass VM | `docker-compose.yml` + local `docker-compose.override.yml` | `docker compose up` by hand |
| **testing / training** | `nsr-sris-dev.quasar.ug` (104.225.218.102) | `compose.prod.yml` | GitHub Actions, automatically on green CI on `main` |
| **production** | `nsr-sris.mglsd.go.ug` (154.72.204.74) | `compose.production.yml` | GitHub Actions, after training succeeds, gated on `PROD_DEPLOY_ENABLED` |

Dev is never deployed to and never deploys anything. Its compose override
is machine-local and `.gitignore`d precisely so it cannot reach a server.

## The flow

```
  feature branch            main                training              production
  us-xxx-short-desc  ──PR──> (protected) ──CI──> auto-deploy ──needs──> auto-deploy
                                                 (canary)               (gated)
```

1. **Branch** off `main`: `us-xxx-short-description`, per CLAUDE.md.
   Short-lived — trunk-based development, not long-running release
   branches.
2. **Commit** anchored to a story: `[US-XXX] short description`.
3. **Open a PR** into `main`. CI runs lint, SAST, unit, contract tests.
   Code review is mandatory.
4. **Merge to `main`.** This is the release action. There is no separate
   release branch and no `develop` branch — `main` is always deployable.
5. **CI runs on `main`.** On success the `Deploy` workflow builds the
   image, tags it `:latest` and `:<commit-sha>`, pushes to GHCR, and
   deploys the **training** box.
6. **Production deploys next**, but only if the training deploy passed
   (`needs: build-and-deploy`) *and* the repository variable
   `PROD_DEPLOY_ENABLED` is `true`. Training is the canary: a deploy that
   breaks it never reaches production.

A red CI run on `main` ships nothing, to either box — the deploy workflow
is gated on `workflow_run.conclusion == 'success'`.

## Why training is the canary, not a staging branch

The alternative — a `develop` branch that deploys to training and a
`main` that deploys to production — means the two boxes run *different
code*, so training stops being a rehearsal for production. Here both
deploy the same commit, minutes apart, and the only difference is that
one has already proved the image boots.

## Production is pinned, training is not

Training runs `NSR_IMAGE=...:latest`. Production pins
`NSR_IMAGE=...:<commit-sha>`, written into `/opt/nsrmis/.env` by the
deploy job. That is what makes a production rollback a one-line edit
rather than a rebuild — see `docs/PRODUCTION.md`.

## Hotfixes

Same path. Branch from `main`, PR, merge. There is no emergency bypass:
the audit trail has to be intact from day one (CLAUDE.md), and a hotfix
that skipped review is exactly the change most likely to need one.

If production must be rolled back *now*, that is a rollback (repoint
`NSR_IMAGE` to the previous SHA), not a hotfix. Roll back first, then fix
forward through the normal flow.

## Branch protection on `main` (to configure in GitHub)

- Require a pull request before merging, with at least one approval.
- Require the `CI` status check to pass.
- Require branches to be up to date before merging.
- No force pushes, no deletions.
