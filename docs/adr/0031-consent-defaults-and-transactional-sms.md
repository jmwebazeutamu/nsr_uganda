# ADR-0031: Consent starts unset, and one SMS is transactional

- **Status**: Accepted — pending DPO ratification
- **Date**: 20 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: Data Protection Officer (MGLSD), NSR Unit Coordinator, Engineering Lead
- **References**: DPPA 2019 §1 (definition of consent), §7 (lawful bases); SAD §8.4; ADR-0024 (consent management module); `docs/dpia.md`; `design/v0.1/screens/consent/consent-capture-block.jsx`, `design/v0.1/screens/consent/consent-shared.jsx`, `design/v0.1/screens/screens-capture.jsx`

---

## Context

Two defects found running households through the parish capture wizard on
19 September 2026 are the same question asked twice, and neither can be
answered by a code change alone.

**A fresh capture opened pre-answered.** "✓ Yes — consented" was already
selected on the registration gate, and four optional purposes — Eligibility
assessment, Programme referral, Payments, Grievance contact — were already
ON. An operator who never mentioned consent, or who asked and was told no
but forgot to click, submitted a record asserting consent on five counts.

**The registry-ID SMS ignored the SMS purpose.** On a household whose SMS
notifications toggle was OFF, the submit dialog still said an SMS would be
sent and the receipt confirmed "An SMS has been queued to the number
recorded for this household."

The second is not simply a bug to fix in one direction. There is a real
argument for sending it: the message carries the respondent's own tracking
number, and without it a respondent who declines marketing SMS is worse off
than one who accepts. There is a real argument against: the registry did
something the respondent had just declined, and said nothing about it.

## Decision

### 1. Every consent-basis purpose starts unset

`defaultConsentBlock()` initialises every purpose whose lawful basis is
Consent — REGISTRATION included — to `""`, not `"GRANTED"`.

DPPA 2019 §1 defines consent as a *"freely given, specific, informed and
unambiguous indication"* by the data subject. A pre-ticked box is an
indication by whoever wrote the form. A default cannot be freely given
because nothing was given.

Three states, not two: **unset** ("not asked"), **granted**, **refused**.
The optional purposes are now a Yes/No pair with neither pre-selected and a
"not asked" badge until one is chosen, because an on/off toggle has no way
to represent the state a fresh form is genuinely in. "Not asked" and "the
respondent said no" are different facts and the registry must be able to
tell them apart — a re-consent campaign needs to know which households were
never asked.

Purposes on a non-consent basis (STATISTICS, under the §7(2)(e) statistical
exemption) stay GRANTED. They are not consent; they apply by operation of
law and have no unset state to be in. They are displayed as such.

`defaultOn` stays on the purpose vocabulary — the citizen portal uses it to
order and recommend purposes — but no longer pre-grants anything at capture.

The Identification validator refuses to advance while REGISTRATION is unset,
with a message that distinguishes it from refusal:

- unset → "Registration consent has not been recorded — ask the respondent"
- refused → "Registration consent was refused — the intake cannot continue"

### 2. The registry-ID receipt SMS is transactional, named, and alone

**One** message is exempt from COMMUNICATIONS_SMS:

| | |
|---|---|
| Code | `REGISTRY_ID_RECEIPT` |
| Content | The provisional Registry ID and how to check status. Nothing else. |
| When | Once, at submission. Never resent automatically. |
| To | The number recorded on this household, if one was recorded. |
| Lawful basis | Public task (DPPA 2019 §7) — delivery of the registration the respondent has just consented to, not a separate processing purpose. |

Everything else — status updates, benefit notifications, programme news,
campaigns — honours COMMUNICATIONS_SMS and is not sent when it is refused or
unset.

The exemption is **named at the point of consent**, not buried. The
registration statement now carries, in the same plain language as the rest:

> If you give us a phone number, we will send you one text message with your
> registry tracking number so you can check your application. That one
> message is part of registering you and is sent even if you say no to text
> messages below. Any other text message from us — programme news, benefit
> updates — is only sent if you agree to "SMS notifications".

And the submit dialog and the receipt say which case this household is in
rather than asserting a flat "An SMS will be sent":

- SMS granted → "One SMS will carry the provisional Registry ID, and the
  respondent has agreed to further SMS updates."
- SMS refused → "One SMS will carry the provisional Registry ID — a service
  message sent as part of registration. No other SMS will be sent: the
  respondent declined SMS notifications."
- SMS unset → the same, ending "SMS notifications were not asked, so no
  other SMS will be sent."

## Why this way

**On the exemption.** Making the tracking number depend on an optional
marketing consent would mean a respondent who declines programme news also
loses the number they need to check their own application — worse for the
data subject than the thing the rule is meant to protect them from. A
one-off service message containing the person's own reference, sent as part
of delivering the service they asked for, is the textbook transactional
case, and it is what every registry, bank and utility does.

**On naming it anyway.** The defect was never really "an SMS was sent". It
was that the registry *silently contradicted* the consent the operator had
just recorded in front of the respondent. An exemption the respondent is
told about at the moment of consent is a disclosed practice. An exemption
they discover from the receipt is a broken promise, whatever its lawful
basis.

**On the scope being this narrow.** Transactional exemptions widen if
nobody holds the line: a status update is arguably transactional, so is a
payment notice, so is a reminder to update your record. One message, one
content definition, one trigger, written down. Anything else is a new ADR.

## Consequences

- Operators must now actively record consent on every capture. This is more
  clicks and it is the point: the click is the record that the question was
  asked.
- Records captured before this change carry consent that may never have been
  given. They are **not** retrospectively valid because this ADR exists.
  Sizing that population and deciding between re-consent and reliance on an
  alternative basis is DPIA work, tracked as **OI-CONSENT-04**, and is not
  resolved here.
- `TRANSACTIONAL_SMS` in `consent-shared.jsx` is the allow-list. A message
  not on it honours the purpose. There is exactly one entry and adding a
  second is an ADR, not a commit.
- **No SMS sending exists in the backend yet.** There is no gateway, no
  queue, no send path — the UI was describing an integration that has never
  been built. This ADR is the specification the integration is built
  against; until it exists, the UI states the intent and nothing is sent.
  Tracked as **OI-SMS-01**.
- DPIA §Lawful basis needs updating for the public-task classification of
  `REGISTRY_ID_RECEIPT` before this ships to a live parish.

## Open items

| Ref | Item | Owner |
|---|---|---|
| OI-CONSENT-04 | Size the population captured under pre-ticked consent; decide re-consent vs alternative basis | DPO |
| OI-SMS-01 | Build the SMS gateway to this specification | Engineering Lead |
| OI-CONSENT-05 | Ratify the public-task classification of `REGISTRY_ID_RECEIPT` and update the DPIA | DPO |

## Alternatives considered

**Honour the toggle for every SMS, including the registry ID.** Cleanest
rule, worst outcome: a respondent who declines SMS notifications gets no
tracking number by SMS, and the printed slip becomes the only copy. Field
ops report slips are lost. Rejected on data-subject interest, not on
convenience.

**Keep the pre-ticked defaults and add a confirmation step.** Preserves the
click-count but not the principle — the record still originates as an
assertion the form made. Rejected.

**Default REGISTRATION unset but leave the optional purposes pre-granted.**
Fixes the headline and keeps the substance of the defect: four purposes
still granted by the form rather than the respondent. Rejected.
