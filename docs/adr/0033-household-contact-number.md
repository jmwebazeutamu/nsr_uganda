# ADR-0033: One household contact number, and what happens when it is empty

- **Status**: Accepted
- **Date**: 20 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer (MGLSD), Engineering Lead
- **References**: ADR-0031 (consent defaults and the transactional SMS); SAD §4.6, §11.2; `apps/data_management/models.py` (`Member.telephone_1`), `design/v0.1/screens/screens-capture.jsx`

---

## Context

The capture wizard asked for a phone number twice.

**Identification → "Phone (E.164)"**, marked required, was an
uncontrolled `<input>`: its value was never read into state and never
posted. **Roster → Person 1 → "Telephone"** was bound, posted, and
persisted to `Member.telephone_1`.

So a household captured with a number typed into the Identification box
and nothing on the roster arrived at the registry with no number at all,
while a household that happened to have both filled appeared to work.
Two boxes, one of them a decoy, and the decoy was the one marked
required.

The consequence was not a blank field. The receipt told the operator:

> One SMS carrying this ID has been queued to the number recorded for
> this household.

asserted on a record holding no number. Either nothing was sent, or
something was sent somewhere the record cannot account for — and neither
the operator nor the respondent could tell which.

## Decision

### 1. The household contact number of record is `Member.telephone_1` of the head of household

One field. Not a new column, and not a second field kept in step with
the first — "kept in step" is what failed here.

`Member.telephone_1` is already the column the registry indexes
(`models.Index(fields=["telephone_1"])`), the one the roster collects,
the one the DIH review panel reads, and the one the UPD change-request
flow edits. Adding `Household.contact_phone` beside it would create two
places a number can live and one of them would go stale.

The Identification box now **writes through to the head member** — the
same value the roster's Person 1 Telephone edits. Editing either edits
the head member's `telephone_1`. There is no copy to diverge, because
there is no copy.

Consequences of that choice, stated plainly:

- The box is **disabled until the head exists** on the Roster tab, and
  says so. There is nowhere to put a number before there is a member to
  attach it to, and silently buffering one into a variable that may
  never be flushed is how this defect happened.
- It is relabelled **"Household phone"**, not "Phone", because it is a
  property of the household record and not of whoever happens to be
  answering.

### 2. The respondent is recorded, but is not the contact number

The respondent — who actually answered the questions — is frequently not
the head: an adult child, a co-wife, a neighbour. That is worth knowing
when a record is later disputed, so `respondent_name` is carried on the
canonical payload and shown on the staged record.

It is **not** a contact number and does not get one. A "respondent
phone" distinct from the household phone would recreate the two-field
problem with a governance question attached: the respondent may not be a
data subject of this household at all, and storing their personal
contact details under the household's record is processing MGLSD has no
basis for. If MGLSD wants the respondent as a first-class entity with
its own contact details and its own lawful basis, that is a schema
change with a DPIA entry — **OI-CONTACT-01**, not this ADR.

### 3. What the SMS sender does when the number is empty

No number is a **legitimate, expected state**, not an error. Many
households have no phone. It must not block a capture and it must not be
misreported.

| | |
|---|---|
| **Capture** | Proceeds. The Registry ID is issued and the slip is printed exactly as it would be otherwise. |
| **Sender** | Sends nothing. No queue entry, no retry, no placeholder recipient. A send attempt against an empty recipient is not a delivery failure to be retried — there is nothing to retry. |
| **Submit dialog** | "No household contact number has been recorded, so no SMS will be sent — the printed slip will be the respondent's only copy of the Registry ID." |
| **Receipt** | "**No SMS has been sent.** This record holds no household contact number, so there is nowhere to send one. The printed slip is the respondent's only copy of this ID — make sure they leave with it." |
| **Slip** | Prints `Contact number: none recorded`, so the respondent can see it and correct it at the desk. |
| **Recovery** | A number can be added to the head member from the DIH review queue and the SMS re-sent from there. |

And when there **is** a number, the receipt and the slip **name it**:
"queued to +256782998877, the household contact number on this record".
A message the operator cannot check is a message the operator has to
take on trust, which is the position the old wording put them in.

This is the `REGISTRY_ID_RECEIPT` message of ADR-0031, and nothing here
changes its lawful basis: it stays transactional, sent once, exempt from
`COMMUNICATIONS_SMS`, and named in the registration consent statement.
ADR-0031 decided *whether* it is sent; this ADR decides *where to*, and
what happens when the answer is nowhere.

## Consequences

- The SMS gateway of **OI-SMS-01** (still unbuilt — there is no sending
  path in the backend at all) is specified against this: recipient is
  the head member's `telephone_1` at time of send; empty recipient is a
  no-op, not a failure.
- `Household.address_narrative` is now collected too. The column existed
  and promotion already wrote it (`payload.get("address_narrative")`);
  nothing had ever collected it, so the review panel showed "Address —"
  on every record in the registry. Adding the field was cheaper than
  removing a row that was wired end to end and merely starved.
- A record captured before this change may hold a number the operator
  typed into the Identification box and believed was saved. It is not
  recoverable — it was never transmitted. Operators should be told, and
  the affected households re-contacted through the parish.

## Alternatives considered

**Add `Household.contact_phone`.** A dedicated column reads cleanly and
creates the exact failure being fixed: two numbers, no rule for which
wins, and a UPD edit to one leaving the other stale. Rejected.

**Keep both boxes and sync them on blur.** Preserves the screen layout
and makes the bug intermittent rather than absent. Rejected.

**Drop the Identification box entirely and collect the number only on
the Roster tab.** Honest and minimal, and it loses something real:
Identification is where the operator is sitting when the respondent
gives their number, before the roster is built. Write-through keeps the
question where the conversation puts it without keeping a second field.
