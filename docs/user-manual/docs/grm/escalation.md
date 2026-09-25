# Escalation and SLA

Every tier gets a window. When it runs out, the case goes up.

## The ladder

```mermaid
flowchart LR
    L1["L1 · Parish Chief<br/><b>24 hours</b>"] --> L2["L2 · CDO<br/><b>48 hours</b>"]
    L2 --> L3["L3 · District M&E<br/><b>72 hours</b>"]
    L3 --> L4["L4 · NSR Unit<br/><b>168 hours</b>"]
    L4 --> STOP["top of the ladder<br/>breach is flagged, not escalated"]
```

!!! note "These windows are configuration"
    An administrator can retune a tier's window without a software
    release. If the numbers above do not match what you see on screen,
    the screen is right — check with your administrator rather than
    this page.

## Escalating by hand

1. Open the case.
2. Click **Escalate one tier**.
3. Pick a **reason** from the list.
4. Add a **note** — at least a few words of context.
5. **Escalate**.

The reason and note go into the audit chain. The next tier reads them
first.

### What escalation does

- Moves the case **up one tier**.
- Sets the status to **Escalated**.
- **Clears the assignee** — the receiving tier decides who takes it.
- **Restarts the clock**. The new tier gets its full window from now.

!!! warning "The clock restarts — this used to be wrong"
    Until September 2026 the SLA was measured from when the case was
    first opened, at every tier. Escalating a case that had already
    blown its L1 deadline handed L2 a deadline in the past. On
    production, cases showed as 2,900 hours overdue at a tier they had
    only just reached.

**Escalate** does not appear on a case at L4, or on one that is
resolved or closed.

## Automatic escalation

A scheduled sweep escalates breached cases on its own.

```mermaid
flowchart TD
    A["Sweep runs"] --> B{"Past its SLA?"}
    B -- no --> Z["left alone"]
    B -- yes --> C{"Already at L4?"}
    C -- yes --> D["flagged once<br/>no further escalation"]
    C -- no --> E["up one tier<br/>actor: system<br/>reason: SLA breached"]
```

One tier per run, so a badly overdue case climbs steadily rather than
jumping to L4 in a single step. An L4 case is flagged once — it does not
re-flag on every sweep.

You will see these in the timeline as **system**, with the reason *SLA
breached*.

## When a case reaches you by escalation

It arrives **unassigned**, with a fresh clock and a reason from the tier
below. Two things to do:

1. Read the escalation reason and the note. That is the previous tier
   telling you why they could not settle it.
2. **Assign it** — to yourself or to somebody at your tier. Until
   somebody owns it, nobody is working it.

Use the **Escalated** quick filter to see everything waiting in this
state.
