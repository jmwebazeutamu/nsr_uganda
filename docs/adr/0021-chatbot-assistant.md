# ADR-0021 — Chatbot Assistant module

**Status**: Proposed
**Date**: 2026-05-25
**Authors**: NSR Unit engineering
**Sprint**: 23 (post DE-build)
**Stories**: US-CHB-001 … US-CHB-005 (proposed — not yet in `/docs/03_backlog.xlsx`; owner to backfill)
**Parent ADRs**: ADR-0010 (coded fields via ChoiceList), ADR-0017 (detail entities as tables)

## Context

Internal staff (Parish Chiefs, district staff, MGLSD ops) currently
consult the user manual (`docs/user-manual/`, mkdocs) for operational
guidance — how to handle a walk-in submission, how a grievance is
routed, what a `DAT-DDUP` tier-1 match means. The manual is 80+ pages
across `field/`, `steward/`, `admin/`, `partner/`, `appendices/`.

Reading time is friction. A retrieval-augmented assistant grounded in
the same manuals would let staff ask "how do I correct a stage record
that failed AC-NIN-FORMAT?" and get a citation back to the canonical
page. Later sprints will extend retrieval to anonymised dataset
summaries (FCS distributions, GRM throughput) so the assistant can
also answer operational-stats questions; that is out of scope here.

The chatbot is not in SAD §4's 12 functional modules. This ADR
proposes it as a **new cross-cutting module** alongside `SEC` /
`RPT` / `REF-DATA`, with the same modular-monolith Django-app layout
the rest of the codebase uses.

## Decision

Create `apps/chatbot/` — a new Django app — implementing a
RAG-grounded chat assistant over the user manuals.

- **Audience**: internal staff only. Behind Keycloak; ABAC scopes
  conversations to `user=request.user`.
- **LLM provider**: **Anthropic Claude**. Default model
  `claude-sonnet-4-6` (1 M context, lower cost than Opus for chat).
  Key read from `ANTHROPIC_API_KEY` via `django-environ`. No key is
  committed (per CLAUDE.md anti-pattern).
- **Retrieval**: **RAG with cosine top-k**. `ManualChunk` table
  holds chunked manual content + a `JSONField` embedding column
  (list of 384 floats). v1 retrieval is Python-side cosine over
  all chunks — the manuals corpus is hundreds of chunks, fits
  comfortably in memory, and skips the pgvector/sqlite portability
  dance. **pgvector graduation**: once the corpus grows past
  ~10 k chunks (i.e. when "datasets later" lands) introduce a
  `pgvector.django.VectorField` migration + IVF/HNSW index; the
  retrieval call site is the only consumer.
- **Embeddings**: **local sentence-transformers**
  (`all-MiniLM-L6-v2`, 384-d). In-process, no second API key, zero
  per-token cost. Model weights ship in the deploy image
  (~80 MB). Anthropic does not publish a hosted embeddings API as
  of this ADR; this avoids introducing a second provider.
- **Persistence**: per-user `Conversation` + `Message` tables with
  ULID PKs. `AuditEvent`s emitted on every prompt send and model
  reply (CLAUDE.md §8.4 — chat content can reference personal data).
- **UI**: dedicated top-level "Assistant" nav entry in the Admin
  Console. Design-harness JSX screen ships first under
  `/design/v0.1/screens/screens-assistant.jsx`; real React wiring
  follows in `apps/admin_console/`.
- **Ingestion**: `python manage.py reindex_chatbot` walks
  `docs/user-manual/docs/**/*.md`, chunks by mkdocs heading, embeds
  via Anthropic, upserts. Re-run at deploy time.
- **Feature flag**: `CHATBOT_ENABLED` defaults `False`. Read
  endpoints stay closed until the flag is flipped (HANDOFF pattern,
  matches `PARTNERS_MODULE_ENABLED`).

## Considered alternatives

- **Long-context (stuff full manuals in the prompt).** Works while
  the corpus is the ~80-page user manual; breaks once "datasets
  later" lands. Keeping RAG from day one avoids a forced rewrite
  and gives us citation back-references for free.

- **OpenSearch (already in the locked stack) as the vector store.**
  Viable. Rejected for v1 because (a) the audit-bearing modules
  already live in Postgres so co-locating the index there keeps
  joins simple, and (b) pgvector is the lowest-ops path to a v1.
  Re-evaluate when corpus exceeds ~10 M chunks or when we need
  hybrid lexical+vector ranking — that's OpenSearch's home turf.

- **OpenAI / multi-provider LiteLLM shim.** Rejected for v1. One
  provider is enough complexity for the first slice; the
  `provider.py` boundary is small enough to swap later without
  touching the API surface.

- **Long-context replacement of RAG once Claude 1 M context is
  available everywhere.** Not yet — pricing per token still favours
  retrieval for chat, and citation UX depends on having discrete
  source chunks to point at.

## Consequences

- New deps: `anthropic>=0.40`, `pgvector>=0.3`. Both flagged in
  `pyproject.toml`. CI runs against sqlite so the pgvector
  extension is a Postgres-prod-only requirement (Helm chart will
  add `CREATE EXTENSION IF NOT EXISTS vector;` before the
  migration runs).
- One additional outbound network dependency (Anthropic API).
  Rate-limit and failure modes need to be tracked in the runbook
  (deferred to CHB-005 follow-up).
- Conversation history holds free-text user content which may
  include personal-data references. DPIA impact to be recorded
  (per CLAUDE.md DoD §6) when CHB-002 ships the models.

## Open items

- **CHB-O-01** — Backlog entries: `/docs/03_backlog.xlsx` has no
  CHB epic. Owner: PM. Action: add US-CHB-001 … US-CHB-005 with
  acceptance criteria before the slice merges to main.
- **CHB-O-02** — DPIA: the DPO needs to sign off on storing user
  prompts + assistant responses. Owner: DPO. Trigger: before
  CHATBOT_ENABLED is flipped in any non-dev environment.
- **CHB-O-03** — ~~Embedding model choice.~~ **Resolved
  2026-05-25** — local `all-MiniLM-L6-v2` via
  `sentence-transformers`. Revisit if retrieval quality is
  inadequate on the manuals corpus (consider Voyage AI
  voyage-3 at that point).
- **CHB-O-04** — Retention policy. Conversations are persisted
  indefinitely in v1; PR follow-up needs a TTL aligned with DPPA
  2019 data-minimisation. Owner: DPO + engineering.
