# Runbook — receiving grievances from STAAC's GRM

**Module:** GRM (`apps/grievance/external`) · **Decision:** ADR-0044 ·
**Contract:** `NSR_STAAC_GRM_API_SPECIFICATION_v1.md` (STAAC repo, v1.1)

This feature is almost entirely operator-mediated recovery. It will
stop, hold records, and wait for a human more often than it will fail,
and every one of those states is deliberate. This page says what each
one means and what to do about it.

The one thing to understand first: **a record this registry cannot
file is held, not dropped.** Held means we received it, stored exactly
what arrived, filed nothing, and recorded why. Nothing is ever lost
waiting for configuration, and nothing has to be re-fetched from STAAC
once the configuration arrives.

---

## 1. Before the first call

Four things must exist. Three are somebody else's to give you.

| What | Who | Where it goes |
|---|---|---|
| A service credential (bearer token) | The IG, through STAAC's partner-access workspace | Django admin → Grievance → STAAC credentials |
| NSR's fixed public egress IP/CIDR on that credential | The IG | STAAC's side only |
| A signed data-provision agreement | MGLSD + the IG | Django admin → Data Integration Hub → Data provision agreements |
| Approved category bindings | MGLSD | Django admin → Reference data → Choice lists → `staac_grievance_category` |

### The credential

Admin → **STAAC credentials** → Add.

- **Environment** — `sandbox` or `production`. Use the real word; the
  pull refuses to choose between two active credentials, deliberately,
  because `production` sorts before `sandbox` and an operator testing
  without the flag would otherwise have made a live partner call.
- **Base URL** — STAAC's origin, no path.
- **Token** — paste once. It is never displayed again; the field is
  blank on every later edit and leaving it blank keeps the stored one.
  Entering a new token clears the saved cursor, because STAAC signs
  cursors per credential.

STAAC shows its token once and then keeps only a digest. If it is lost,
the IG issues a replacement; it cannot be recovered.

### The agreement

Admin → **Data provision agreements** → Add, against source system
`STAAC_GRM`.

- **Reference** must match the `agreement_reference` STAAC puts in its
  snapshots, character for character. If it does not, every record is
  held with reason *unverified agreement* — the registry is refusing
  to take the partner's word for what it is permitted to receive.
- **Valid from / valid to** gate it by date. An expired agreement holds
  records the same way.

Without any agreement the pull does not start at all, and the push
receiver answers `503`. That is the intended order: no agreement, no
personal data received.

### The category bindings

STAAC classifies with sixteen categories; NSR has six. The
correspondence is a policy statement, so it ships empty and every case
is held with reason *unbound category* until somebody sets it.

Admin → Choice lists → `staac_grievance_category` → each option →
**Canonical code** → one of `data_correction`, `exclusion_error`,
`inclusion_error`, `programme_issue`, `operator_conduct`, `other`.

Then run `--file-held` (§3) to file what arrived while they were
unbound.

---

## 2. Running a pull

```
.venv/bin/python manage.py pull_staac_handovers --environment sandbox
```

Output is one summary line, then warnings, then errors:

```
2 page(s), 6 listed, 6 fetched, 5 filed, 1 held, 0 already had
correlation id: 2c4c0a1a-...
```

- **listed** — rows STAAC offered.
- **fetched** — snapshots retrieved. Lower than *listed* is normal on a
  re-run: records already held are not fetched again, because
  re-reading a snapshot re-reads a complainant's identity for nothing.
- **filed** — became a grievance.
- **held** — stored, not filed. See §3.
- **already had** — recognised from a previous run.

Quote the **correlation id** in anything you send the IG; STAAC logs
the same value.

Every run writes a `ConnectorRun` (admin → Data Integration Hub →
Connector runs), so "did last night's pull work" is answerable without
the terminal output. A run with errors is recorded `failed` and does
**not** update the credential's *last pulled* time — a fresh timestamp
on a run that imported nothing is the reassuring kind of wrong.

### Useful flags

| Flag | When |
|---|---|
| `--limit N` | Page size, 1–200. Lower it only to debug. |
| `--changed-since` | RFC 3339 UTC. First request only; ignored when resuming. |
| `--restart` | Ignore the stored cursor and read the collection from the start. Safe: records already held are recognised and skipped. |
| `--file-held` | Do not call STAAC at all. Re-apply the mapping to what is already stored. |

---

## 3. Held records — the normal case

Admin → **STAAC handovers**, filter **Outcome = held**. The *held
reason* column groups them:

| Reason | What happened | What to do |
|---|---|---|
| `unbound_category` | We know the STAAC category; nobody has said what it means here | Get the binding approved (§1), then `--file-held` |
| `unknown_category` | STAAC sent a category not in our list — their taxonomy changed | Tell the IG, then reseed `staac_grievance_category` |
| `unresolved_place` | `parish_key` names no GeographicUnit | Check the code against reference data; it may be a new unit we have not loaded |
| `unverified_agreement` | The snapshot cites an agreement we do not hold in force | §1 — do **not** work around this one |
| `refused` | Something else; read *outcome detail* | Case by case |

The *held source code* column is the thing to go and fix — the STAAC
category code, or the unresolved geography key. Group by it to see
which single binding unblocks the most cases.

```
.venv/bin/python manage.py pull_staac_handovers --file-held
```

Re-applies the current mapping to every held snapshot. Nothing is
re-fetched, and a filed case's SLA still runs from when the
complainant reported — not from when the binding was approved.

---

## 4. When something is wrong

**"No active STAAC credential is configured"** — §1, or the row is
marked inactive.

**"More than one active STAAC credential (production, sandbox)"** —
pass `--environment`. This is a refusal to guess, not a fault.

**"no active DPA for source STAAC_GRM"** — §1. The pull stopped before
making any call.

**401 "STAAC refused the credential"** — token missing, expired,
revoked, *or* the call came from an address the IG has not approved.
STAAC answers both the same way on purpose. Check the token's expiry
first, then confirm this host's public egress IP is still the one on
the credential. Notify the IG **before** changing NSR's egress address.

**403** — the credential lacks `partner:handover:list` or
`partner:handover:read`. IG administrator.

**"restarted from the beginning"** in the warnings — STAAC rejected
the stored cursor, which usually means a key rotation on their side.
Harmless: the run restarted and skipped everything already held.

**"A record on this page could not be stored"** — one snapshot could
not be read, so the cursor was deliberately **not** advanced and the
next run re-reads that page. Do not clear the cursor to "get past it":
advancing past a record STAAC will never offer again loses the
complaint permanently. Read the error, fix the cause, run again.

**429** — rate limited. The client already backs off with jitter and
honours `Retry-After`. Persistent 429 is a conversation with the IG
about the agreed rate.

---

## 5. Push (not active)

`POST /api/v1/grm/partners/staac/handovers/` exists and refuses
everything until `GRM_STAAC_PUSH_SECRET` is set, because the partner
contract §6.1 leaves the receiver's authentication profile — mTLS,
client certificates, or a STAAC-issued token — to be agreed between
the IG and NSR. Do not set that secret to "turn push on" unilaterally.

When it is agreed: set the secret from the secrets store (never in
`.env` committed anywhere), restrict inbound traffic to STAAC's egress
ranges at the gateway, and confirm with a synthetic handover. Pull
remains the required reconciliation path either way — push is an
optimisation over it and shares the same storage, agreement gate and
idempotency key, so a record arriving both ways is one record.

---

## 6. What this registry must never do

From the contract, §1 and §9:

- **Do not close a STAAC case.** The IG records feedback to the
  complainant and performs closure. A grievance filed here is NSR's to
  investigate within its mandate, not to resolve on STAAC's behalf.
- **Do not query STAAC by tracking number** or scan its cases. The
  collection is the only entry point.
- **Do not create a second record for a repeat delivery.**
- **Do not report status or outcome back** over this API. There is no
  callback in v1.
- **Do not log the bearer token, a payload, an identity field or a
  narrative** (§7).
