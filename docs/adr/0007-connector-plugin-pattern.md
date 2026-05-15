# ADR-0007: DIH connector plug-in pattern (admin-driven credentialing)

- **Status**: Accepted (Sprint 11)
- **Date**: 2026-05-15
- **Owner**: NSR MIS Architecture Team
- **References**: SAD §4.6 (DIH pipeline), ADR-0001 (modular monolith + separately deployable DIH), ADR-0002 (ULID identifiers, ConnectorRun), `/CLAUDE.md` (Auth: Keycloak; "Do not commit .env or any KMS-managed secret"), US-S8-005 (connector framework — shared base + registry), US-S11-003 (Kobo connector + admin UI)

---

## Context

DIH onboards an open-ended set of upstream sources. Sprint 0 wired four
canonicalisation-only connectors (PDM, NUSAF, WFP SCOPE, NIRA reverse-
feed) — each takes a payload, transforms it into the canonical NSR
shape, and returns it. They share a single `Connector` Protocol and
get registered into a process-level `CONNECTOR_REGISTRY` at import
time (US-S8-005).

Sprint 11 introduces Kobo Toolbox, which is fundamentally different:
the registry needs to **reach out** to a Kobo HTTP endpoint, with
operator-supplied credentials, on demand. The original Protocol has
no `test_connection`, no `list_forms`, no `pull_submissions`. The
existing seed script ships a `KOBO-PILOT` SourceSystem row but there
is no way for an operator to wire its credentials — neither
`/CLAUDE.md`'s anti-pattern "Do not commit .env or any KMS-managed
secret" nor SAD §8 audit requirements allow secrets in the repo or
in a settings file.

US-S11-003's prompt asks for a Django-admin-driven flow where:

1. An operator picks a connector kind (Kobo today; NIRA + UBOS
   marked "coming soon" but already visible).
2. They enter the upstream URL + their Kobo username + password.
3. The system exchanges the password for a Knox token, stores the
   **encrypted token only**, and offers a "Test connection" button
   that probes the upstream and writes an audit-bearing
   `ConnectorRun` row.
4. NIRA and UBOS plug in later by dropping in a `*Credential` model
   and a credential form — no churn on the registry or the
   dispatcher.

Three design tensions surfaced and needed pinning down:

- **Where do live methods live — extend the existing Protocol, or
  introduce a sibling LiveConnector?** Two registries means two
  lookups in the DIH dispatcher; one Protocol with optional methods
  means a runtime `None` check.
- **How do credentials get stored when KMS isn't provisioned yet?**
  US-S2-004 is still pending. Production wants AWS KMS envelope
  encryption per NSR-O-04, but the realm hasn't been built.
- **How do operator-driven test runs get audited without skewing
  the import-latency dashboards (S6-005)?** Every `Connector.test_
  connection()` is a real run, but it's not an import; it's a
  probe.

---

## Decision

### 1. Extend the existing Protocol with optional methods; keep one registry.

`apps/ingestion_hub/connectors/base.py` gains three optional
methods on the `Connector` Protocol:

```python
class Connector(Protocol):
    code: str
    def canonicalize(self, raw: dict) -> dict: ...
    def process(self, raw: dict, *, actor: str) -> Any: ...
    def test_connection(self, credentials: dict) -> ConnectionTestResult: ...
    def list_forms(self, credentials: dict) -> list[dict]: ...
    def pull_submissions(self, credentials: dict, *,
                         form_id: str, since: str | None = None) -> Iterator[dict]: ...
```

The four canonicalisation-only connectors leave the new methods set
to `None` (no behaviour change). KoboConnector populates all three.
Callers that need a live method (the `connection_test` service,
future schedule-builder) check `is None` before calling.

**Rejected**: a sibling `LiveConnector` Protocol with its own
`LIVE_CONNECTOR_REGISTRY`. Pros: stronger type signal; the OpenAPI
enum for "kinds that have Test connection" would just be a registry
dump. Cons: two registries means two lookups in any pipeline-aware
code, and the four existing canonicalisation connectors would need
either (a) a no-op live counterpart or (b) the dispatcher would
need to check both registries. The optional-method approach keeps
the dispatcher single-pass.

### 2. Credentials stored via `EncryptedBinaryField` today; KMS-swap when US-S2-004 lands.

Each connector that needs runtime credentials brings a
`*Credential` model (one row per SourceSystem, OneToOne). The first
implementation:

```python
class KoboCredential(models.Model):
    source_system = models.OneToOneField(SourceSystem, ...)
    server_url = models.URLField(...)
    token_encrypted = EncryptedBinaryField()   # Fernet today
    acquired_by_username = models.CharField(...)
    acquired_at = models.DateTimeField(auto_now_add=True)
    last_test_at = models.DateTimeField(null=True)
    last_test_ok = models.BooleanField(null=True)
```

`EncryptedBinaryField` is the same column type used for `Member.
nin_value` — a Fernet round-trip in
`apps/security/encryption.py`. When US-S2-004 swaps the
implementation to AWS KMS envelope encryption, every
`EncryptedBinaryField` column upgrades at once with no migration on
the dependent models. Field stays bytes-in/bytes-out; the call site
doesn't change.

**Plaintext usernames are recorded** in `acquired_by_username` for
audit-chain lineage (which operator's identity is reaching the
upstream API). **Plaintext passwords are never persisted** — they
live in the request handler's stack frame while
`acquire_token(username, password)` exchanges them for a Knox
token; after the token comes back, the password is discarded.

### 3. `ConnectorRun.run_type` separates test probes from import runs.

The existing `ConnectorRun` model gains a `run_type` field
(`IMPORT` default; `TEST` for admin-driven probes). Every test
attempt writes a `ConnectorRun(run_type=TEST)` plus an
`AuditEvent(action='test_connection', actor_kind='user')`. Two
operational properties fall out:

- **Audit chain intact.** Even a failed probe is recoverable from
  AuditEvent + ConnectorRun.note (the failure reason is recorded
  verbatim). Per CLAUDE.md "the registry must be reconstructable
  from the audit chain."
- **Dashboards stay honest.** The promotion-latency aggregator in
  RPT (S6-005) filters on `run_type=IMPORT`; test probes don't
  drag medians sideways. The new
  `Index(fields=["run_type", "started_at"])` keeps that query fast
  even at full national load.

### 4. Plug-in seam = `_CREDENTIAL_REGISTRY` in `admin_credentials.py`.

```python
_CREDENTIAL_REGISTRY: dict[SourceSystemKind, type[StackedInline]] = {
    SourceSystemKind.KOBO: KoboCredentialInline,
}
```

NIRA and UBOS join by:

1. Add a `NiraCredential` (or `UbosCredential`) model with the
   relevant fields and `EncryptedBinaryField` for any secret.
2. Add a corresponding `NiraCredentialForm` / `NiraCredentialInline`
   (analogue of `KoboCredentialForm` / `KoboCredentialInline`).
3. Append an entry to `_CREDENTIAL_REGISTRY`.
4. Add an `elif source_system.kind == ...` branch to
   `credentials_for()` in `connection_test.py`.
5. Move the kind out of the implicit "(coming soon)" set in the
   `SourceSystemForm.__init__` override (the `SUPPORTED_KINDS`
   constant in `admin_credentials.py`).

No churn on the Protocol, the registry, the connector code itself,
or on the four canonicalisation connectors.

---

## Consequences

### Positive

- **One registry, one Protocol.** `get_connector(code)` still
  returns the right object whether the caller needs canonicalize or
  test_connection; pipeline code doesn't fork.
- **Audit chain covers operator probes.** ConnectorRun rows of
  type=TEST + AuditEvent(test_connection) reconstruct every probe
  attempt for the DPO.
- **KMS swap is one-file.** All Fernet ciphertext columns flip to
  KMS-envelope when `apps/security/encryption.py` learns the new
  client; no migration on KoboCredential, Member, or any future
  `*Credential` model.
- **Operators see what's coming.** The dropdown lists NIRA and
  UBOS as `(coming soon)` rather than hiding them — feedback that
  the work is planned, just not done.

### Negative

- **Runtime `None` checks instead of compile-time guarantees.**
  Any caller of `connector.test_connection(...)` must first check
  the attribute isn't `None`. The price of the single-registry
  decision is paid here.
- **Plaintext password transits in-memory through the Django form
  layer.** Mitigations: `widget=PasswordInput(render_value=False)`
  prevents echo-back to the browser; `acquire_token()` keeps it in
  a local; no logging hook captures the form's `cleaned_data`. The
  remaining surface is a memory dump of the running Python process,
  which is in scope for the KMS work (NSR-O-04) but accepted as a
  residual risk for the Sprint 11 pilot.
- **Per-connector dispatch in `credentials_for()`.** An `if/elif`
  chain keyed on `SourceSystemKind`. Acceptable while there are 1-3
  live connectors; revisit if we cross 6 (move dispatch onto the
  connector class itself, e.g.
  `connector.read_credentials(source_system)`).

### Operational notes

- **Storage**: `KoboCredential.token_encrypted` holds Fernet
  ciphertext today. The plaintext is the Kobo Knox token string,
  UTF-8 encoded. Rotation is a re-save through the admin form (the
  Knox endpoint will mint a new token even with the same
  username+password).
- **Token revocation**: when a credential row is deleted, Knox
  tokens stay valid upstream until the user revokes them in
  Kobo. The admin description on `KoboCredential` should call this
  out to operators (TODO).
- **Test endpoint**: `Connector.test_connection()` uses
  `GET /api/v2/assets.json?limit=1` — read-only, idempotent, cheap
  on the upstream side. Allowed under any DPA scope that grants
  list access.
- **Retry budget**: three attempts at 1s/3s backoff means a
  worst-case "Test connection" round-trip of ~30s; admin UI shows
  a spinner until the response lands.

---

## Open questions

| ID | Question | Owner | Resolved by |
|---|---|---|---|
| DIH-O-CONN-01 | Should `test_connection` write to RawLanding (zero rows) to confirm the landing pipeline AND the network path? | DIH lead | When the schedule-builder lands (US-S12-?) |
| DIH-O-CONN-02 | How do we revoke a Kobo token upstream when KoboCredential is deleted? Requires a DELETE call to the Kobo `/api/v2/users/{user}/api_token/` endpoint. | DIH lead + Operations | When the Kobo MoU is signed |
| DIH-O-CONN-03 | What ABAC rule constrains *who* can mint a credential? Today: any Django staff user. Should be: SEC role `dih_credential_admin`. | Security + Architecture | Closes with US-S2-002 (Keycloak realm + role catalogue) |

---

End of ADR-0007.
