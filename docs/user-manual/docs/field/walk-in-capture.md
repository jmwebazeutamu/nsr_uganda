# Walk-in household capture

!!! info "Status"
    **Built and in use** — desktop capture screen ships in `screens-capture.jsx → CaptureScreen device="desktop"`. CAPI tablet variant renders via `<CapturePadCAPI>`; tablet sync is **Scaffolded** pending [ADR-0004](../appendices/adrs.md).

A walk-in is when a head of household visits your parish office. You sit them down, ask the questions, and submit.

## Before you start

- Confirm the visitor is the head of household, or holds the head's authorisation.
- Ask for their National ID (NIN) and any household member NINs they have.
- Have a working internet connection for the desktop console. (For offline capture, use the CAPI tablet.)

## The capture flow

| Step | Section | What you collect |
|---|---|---|
| 1 | Identification | Household name, head NIN, contact phone |
| 2 | Location | Region down to village, GPS reading |
| 3 | Members | One row per member: name, NIN if any, sex, DOB, relationship to head |
| 4 | Dwelling | House type, walls, roof, water source, sanitation |
| 5 | Utilities | Electricity, fuel for cooking, lighting |
| 6 | Food and shocks | FIES, FCS, recent shocks, coping strategies |
| 7 | Consent | DPPA 2019 consent text, head signs |

The top stepper shows completion ticks per section. The left rail is keyboard-reachable; arrow keys move you between sections.

## Live validation

The right rail shows a live count: "N warnings, M blocking failures". You cannot submit while M > 0.

The three Sprint 0 rules fire here:

| Rule | Effect |
|---|---|
| `AC-MANDATORY-MEMBER-NAME` | Blocks until every required field is filled |
| `AC-NIN-FORMAT` | Blocks if NIN does not match `^(CM\|CF)[A-Z0-9]{12}$` |
| `AC-GPS-ACCURACY` | Blocks until GPS accuracy is 10 m or better |

For GPS, if accuracy is worse than 10 m, the reading shows in red with "Move to an open area and retry".

## Photo and GPS capture

- **Photo capture**: click the photo button. It opens the device camera. The image is uploaded and an `evidence_ref` lands in the form state.
- **GPS capture**: click the GPS button. Lat, lng, and accuracy are displayed live. The GPS reading is required for promotion.

## Submitting

When all sections are filled and zero blocking failures remain, the **Submit for promotion** button enables.

On submit:

1. The record lands in DIH as `pending_review` (or auto-promotes via fast-track if it has zero candidates).
2. A provisional Registry ID (ULID) is generated.
3. The receipt screen shows next, with a printable A6 slip and an SMS preview.

## The receipt slip

The slip carries seven content blocks (per UI Brief §11.2):

1. Title: "NSR Provisional Registry Receipt"
2. Provisional Registry ID in monospace
3. Head of household name
4. Parish + Sub-county + District
5. Date and EAT time
6. Operator name + station
7. DPPA 2019 footer line

The SMS preview is at most 160 characters and contains the Registry ID, the date, and a contact line.

## What happens next

| Outcome | Visible to you when |
|---|---|
| Fast-track auto-promote | Within minutes; status becomes `registered` |
| Awaiting steward review | If DDUP found a candidate or DQA fired warnings |
| Quarantined | If a blocking failure slipped through (it shouldn't, but does happen on edge cases) |

If your record is quarantined, you receive a GRM ticket. Open it, see the reason, correct the data, and resubmit.

## Related

- [Household lookup](household-lookup.md) — to confirm a record promoted
- [Grievances (GRM)](grievances.md) — to handle a citizen complaint
- US-088, US-112 acceptance criteria in `/design/v0.1/acceptance.md`
