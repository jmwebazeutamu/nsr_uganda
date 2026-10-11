# DPIA — receiving grievances from STAAC's GRM

**Status**: For DPO review. Nothing has been exchanged with a live
partner; this records the design before activation, not after.
**Last updated**: 2026-10-11.
**Covers**: `apps/grievance/external` (pull client and push receiver),
`StaacHandover`, `StaacCredential`, `GrievanceAttachment`, and the
`reporter_gender` / `reporter_age_years` columns on `Grievance`.
**Parent document**: `/docs/dpia.md`.
**Related**: ADR-0044, `infrastructure/runbooks/staac-grievance-exchange.md`.

---

## 1. What changes

NSR begins receiving personal data **from another controller**. Every
previous instalment covers data this registry collected itself or
received from a statistical source. This is the first routine inbound
flow of named individuals from a separate organisation — the
Inspectorate of Government — about people who complained to *them*.

A complainant who telephoned the IG about being left off the NSR list
has their name, phone number, sex, age, location and the account they
gave, copied into this registry. They did not give it to MGLSD. Most
will not know the transfer happened.

## 2. The data

| Category | Fields | Source |
|---|---|---|
| Identity | given name, family name | STAAC snapshot, where the approved manifest permits |
| Contact | phone | same |
| Demographic | sex, age in years | same |
| Location | a geography key, resolved here to the seven scope columns | same |
| Narrative | the complainant's own account of what happened | same |
| Provenance | tracking number, handover id, exchange version, ETag, correlation id, retrieval time, the disclosure manifest | the exchange itself |

Special-category data is **not** expected but is not structurally
excluded: a free-text narrative can contain anything the complainant
said, including health or ethnicity. STAAC seals its GBV/SEA/SH
category so those cases cannot be handed over at all, which removes
the most foreseeable case. The residual risk is a narrative that
mentions something sensitive in passing, and it is not mitigated by
any field-level control — only by the access controls in §5.

## 3. Lawful basis and the transfer

The exchange runs under a data-provision agreement between MGLSD and
the IG. Two controls make that more than a statement:

- The registry will not open a connector run — and therefore will not
  make the first call — unless an agreement covering this source is
  recorded here and in force (`AC-DIH-DPA-REQUIRED`).
- Each snapshot names the agreement it was released under, and that
  reference is checked against the registry's own register. A snapshot
  citing an agreement we do not hold is **stored and not filed**. The
  registry does not take the partner's word for what it may receive.

Each snapshot also carries `shared_data.fields` — the list of identity
fields STAAC was permitted to disclose for that one handover. It is
stored per record, because it is the evidence of what was authorised
at the moment of disclosure and cannot be reconstructed from the
agreement afterwards.

**Open for the DPO.** Whether the complainant is told. The IG takes the
complaint and the privacy notice they are read is the IG's. Nothing in
this design informs the data subject that their complaint has been
transferred to MGLSD, and DPPA 2019 §12 obligations on this controller
start the moment we hold the record. This needs a decision between the
two organisations; it is not a code change.

## 4. Minimisation

What the design does **not** do, deliberately:

- It never asks STAAC for a case. There is no search, no lookup by
  tracking number, no bulk export — only the collection STAAC offers,
  which contains solely what the IG has approved for NSR.
- It does not re-fetch. A handover already held is recognised by
  `(handover_id, exchange_version)` and skipped, so a reconciliation
  run does not re-read a complainant's identity to learn nothing.
- It does not infer. A `null` gender or age is retained as *not
  recorded* rather than defaulted; an anonymous complaint
  (`identity_recorded: false`) produces a grievance naming nobody; no
  attempt is made to match a complainant to a household or member.
- It does not store what it cannot use. Severity has no NSR field and
  is left in the snapshot rather than given a column.

What it *does* keep, which is more than the Grievance needs: the
verbatim snapshot. That is a second copy of the complainant's identity
and narrative, in `RawLanding`. It is kept because a mapping corrected
later must be re-applied to what actually arrived rather than to a
reconstruction — the same reason DIH keeps raw landings for household
intake. **It inherits DIH's retention question and does not answer
it**: `DataProvisionAgreement.residence_policy_days` exists, and
nothing in this feature enforces it. See §7.

## 5. Access and audit

Grievances from STAAC are scoped exactly like any other: the parish
key resolves to the seven geography columns `apps.security.abac`
filters on, so a Kalangala case reaches Kalangala officers. This was
the single most consequential control in the design — a case filed
with blank geography would have been visible to every officer
nationally, and the code refuses to file one rather than risk it.

Audit, through the hash-linked chain:

- a `read` when a snapshot is retrieved, recording the handover id,
  version, ETag, correlation id and the disclosure manifest — **never
  the disclosed values**;
- a `create` when it becomes a grievance;
- an `update` when it is held, naming the reason;
- `create` on each attachment, identified by digest, so the chain
  records that a document exists without embedding a complainant's
  photograph in it.

The bearer credential is held encrypted and is never logged, never
placed in a URL and never put in an exception message.

## 6. New personal data at rest — attachments

`GrievanceAttachment` lets a case carry a photograph or a scan, stored
by content hash in the shared evidence store. Two notes for the DPO:

- The partner contract transfers no files in v1, so this capability is
  presently exercised only by NSR operators through the console.
- The store is file-backed in production today
  (`UPD_EVIDENCE_DIR` on a mounted volume); the MinIO backend is a
  stub. Encryption at rest therefore depends on the volume, not the
  application. That is pre-existing for change-request evidence and is
  now also true of grievance evidence, which may include images of
  identifiable people.

## 7. Risks, and what is not mitigated

| Risk | Status |
|---|---|
| Transfer not disclosed to the complainant | **Open** — §3, needs an MGLSD/IG decision |
| Retention of the raw snapshot | **Open** — no deletion path; inherits DIH's `residence_policy_days`, which nothing enforces |
| Sensitive content inside a free-text narrative | **Partially mitigated** — STAAC seals GBV/SEA/SH; residual risk accepted, controlled by access scope |
| Evidence-store encryption at rest | **Open** — volume-level only, pre-existing |
| Misclassification sending a case to the wrong officers | **Mitigated** — an unmappable category is held, never defaulted to `other`; an unresolvable place is held, never filed blank |
| Credential compromise | **Mitigated** — encrypted at rest, entered once, never displayed; IG revokes and reissues; STAAC additionally restricts by source IP |
| A second copy of identity in the landing table | **Accepted** — justified in §4, bounded by §7's retention question |

## 8. Recommendation

The flow is safe to activate in a sandbox against synthetic data. The
DPO should take a view on §3 (informing the complainant) and §7
(retention of the raw snapshot) **before** any exchange carrying a real
person's complaint, since both are obligations that attach on receipt
and neither is enforced by code today.
