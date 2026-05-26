# CAPI tablet

!!! info "Status"
    **Planned (S8+)** — form runtime decision is open (DDUP-O-02 in `/docs/01_solution_architecture.docx` §12, also [ADR-0004](../appendices/adrs.md)). The tablet variant of the capture screen (`<CapturePadCAPI>`) is built for design preview only. Live offline sync, the SQLCipher local store, and field enumerator login flows are not yet wired.

The CAPI tablet is the field-channel for household capture. You use it when you visit a household for census or recertification, when there is no internet at the parish office, or when the volume of capture is too high for a desktop.

This page describes what we plan to ship and what's stub-only today. Treat the procedure as **forward-looking**.

## Hardware

| Spec | Target |
|---|---|
| OS | Android 12+ |
| Storage | 64 GB |
| Display | 10.1" landscape, 720p minimum |
| Battery | 8 hours nominal |
| GPS | 5 m accuracy or better |
| Camera | 5 MP rear, autofocus |
| Connectivity | LTE optional, Wi-Fi mandatory for sync |
| Cradle | A6 thermal printer dock at the parish office |

## The app (Planned)

Kotlin Android app with SQLCipher local store. Form runtime is the open question:

- **Option A** — XLSForm runtime (Kobo-style). Operator workflow familiar to enumerators trained on Kobo. Less coupling to NSR-specific UI.
- **Option B** — Server-driven React Native UI rendering forms from the questionnaire authoring tool (US-116 to US-120). Tighter coupling, smoother UX, full DQA preview.

The decision lands in ADR-0004 when DDUP-O-02 closes.

## Operator login (Planned)

OIDC PKCE + device flow against the `nsr-mis-capi` Keycloak client. The device flow lets the tablet bootstrap an operator without a browser. Tokens are stored in the SQLCipher local DB and refreshed on every sync.

## Capture (Planned, stub UI today)

The CAPI variant renders one question per screen at 720 px landscape:

- Bottom bar: Back / Next / Save & Exit, reachable with the thumb at any orientation.
- Offline indicator appears when `navigator.onLine = false`.
- Photo and GPS capture as on desktop.

The on-screen DQA runs client-side rules marked `client_side_safe`. Server-only rules fire at sync.

## Sync (Planned)

- Push: new captures upload to the DIH `capi_walkin` endpoint.
- Pull: routing matrix + ChoiceList + DQA rule pack.
- Conflict resolution: last-write-wins is forbidden. Every conflict opens an UPD.

## Receipt slip at the cradle

Once docked, the captures sync. For each promoted record, the cradle's A6 thermal printer produces the receipt slip with the final Registry ID.

## Until CAPI ships

- For walk-ins: use the desktop console.
- For field visits in low-connectivity areas: a printed paper form follows the questionnaire v2 structure (`/docs/06_questionnaire.docx`). Manual entry from paper happens later at the parish office.

## Related

- [Walk-in household capture](walk-in-capture.md) — the desktop equivalent for now
- ADR-0004 — CAPI form runtime decision
- DDUP-O-02 — open item in the SAD
