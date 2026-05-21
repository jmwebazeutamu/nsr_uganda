# ADR-0019 — Sensitive health data column-level encryption

**Status**: Proposed
**Date**: 2026-05-21
**Authors**: NSR Unit engineering
**Sprint**: 22 (DE build)
**Stories**: US-S22-DE-01
**Parent ADRs**: ADR-0002 (identifier strategy; NIN encryption
precedent)

## Context

Question D2 of the questionnaire asks members "from what type of
chronic illness does [NAME] suffer from? [select all that apply]"
with HIV/AIDS, tuberculosis, and other categories. Under Uganda's
**Data Protection and Privacy Act 2019 §§9–10** these are **special
category data** — health, HIV status — and require explicit consent
and additional protection over and above the general personal-data
regime.

The Member.nin_value column already uses an
`EncryptedBinaryField` (ADR-0002) — symmetric encryption via the
project KMS key, application-layer encrypt/decrypt, with `nin_hash`
serving as the join key and `nin_last4` as the masked display.

We need a comparable solution for the chronic-illness types list
because:

1. The list MAY contain HIV / TB codes — but only in some rows.
2. Plain JSONField storage would expose those codes via any
   incidental DB dump, backup, or audit join.
3. Per-code conditional encryption is awkward — encrypting only
   "HIV" entries leaves the column shape inconsistent.

## Decision

**Encrypt the whole `chronic_illness_types` list** on the
`apps.data_management.Health` model, regardless of which codes
it contains. Storage:

- `chronic_illness_types_encrypted = EncryptedBinaryField(null=True, blank=True)`
- Application layer JSON-serialises the `list[str]` → `bytes`,
  the field's prep code encrypts before writing.
- `Health.get_chronic_illness_types() -> list[str]` decrypts and
  parses on read.
- `Health.set_chronic_illness_types(codes)` encodes + assigns;
  caller saves.

The `chronic_illness_flag` column (D1: yes/no/dontknow whether
the member has *any* chronic illness) stays plain — it's
sensitivity Personal, not Sensitive — and gates whether the
encrypted list is meaningful.

## Considered alternatives

- **Encrypt only HIV / TB sub-codes via conditional encryption
  per element.** Rejected — implementation surface explodes
  (serializer needs to selectively encrypt; SQL queries can't
  pattern-match across mixed encrypted + plain JSON elements;
  the type system can't statically declare which codes are
  sensitive); and any non-sensitive code that gets reclassified
  as sensitive (legal interpretation drift) leaves orphan
  plaintext rows.

- **Row-level encryption: the whole Health row.** Tempting but
  rejected — joins on Health.member would need decryption,
  killing reporting performance.

- **Don't capture chronic illness types at all.** Out of scope
  for this ADR; the questionnaire collects them, the registry
  has to store them.

## Consequences

**Gains**

- DPPA 2019 §9 compliance for HIV/TB-relevant data — no
  plaintext in the DB, no plaintext in backups.
- Consistent with the existing nin_value pattern; one KMS key
  rotation covers both surfaces.
- DRS query builder surfaces the column with
  `requires_special_scope=True` (US-S22-DE-09) so partners
  must hold an explicit DSA clause to query against it.

**Costs**

- Cannot index or query inside `chronic_illness_types_encrypted`.
  A query like "all members with HIV code" requires decrypting
  every row — only the DPO would run that, and never as an
  online query.
- Round-trip encryption + JSON parse adds CPU on every Health
  read. Per the existing nin_value precedent the cost is small
  enough to ignore in a 12 M-row registry.
- `chronic_illness_flag` (the boolean answer) IS plain — a row
  with `chronic_illness_flag="1"` and an empty
  `chronic_illness_types_encrypted` reveals that the member has
  *some* chronic illness even if the type list is missing.
  Acceptable: the flag itself is Personal data, not Sensitive.

## References

- DPPA 2019 §9, §10
- ADR-0002 (identifier strategy)
- `apps/data_management/models.py` — `Health` model
- US-S22-DE-09 (DRS scope flag)
