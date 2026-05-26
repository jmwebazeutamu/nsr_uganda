# Parish Chief / Field officer guide

You are here to capture households, look them up, log grievances, and request updates. Most of your work happens at the parish office or on a CAPI tablet during a household visit.

!!! info "Status"
    The console-side walk-in capture, household lookup, and grievance intake are **Built and in use**. The CAPI tablet runtime decision is open ([ADR-0004](../appendices/adrs.md) — DDUP-O-02 pending). Most CAPI offline flows are **Planned** for S8+.

## What you do day-to-day

| Task | Page |
|---|---|
| Capture a walk-in household | [Walk-in household capture](walk-in-capture.md) |
| Look up a household record | [Household lookup](household-lookup.md) |
| Log a grievance from a citizen | [Grievances (GRM)](grievances.md) |
| Request a change to an existing household | [Update requests](update-requests.md) |
| Use the CAPI tablet in the field | [CAPI tablet](capi-tablet.md) |

## Principles you should know

- **Every household has a Registry ID.** When you capture a walk-in, the system prints a provisional Registry ID receipt. The final ID is the same ULID; the "provisional" wording goes away once the record promotes through DIH.
- **You sign your work.** Every save records your username, the time in EAT, your geographic scope, and your IP.
- **You cannot see outside your scope.** If you are a Parish Chief, you only see households in your parish. A District CDO sees the whole district. National-scope roles (NSR Unit, DPO) see everything.
- **The receipt is the proof.** Always print or SMS the receipt slip to the head of household. It carries the Registry ID, the date, the operator name, and the DPPA 2019 footer.

## Languages

The console renders in English and Luganda. Other Ugandan languages are Planned with US-117 (questionnaire authoring). For now, render-time language picks from the user's profile.

## Devices

| Device | Where | Status |
|---|---|---|
| Desktop console | Parish office | Built |
| Laptop console | District office | Built |
| Android tablet (CAPI) | Field, offline-capable | Scaffolded (runtime decision pending) |
| Thermal receipt printer | Parish office | Built (A6 layout at 200 dpi) |
