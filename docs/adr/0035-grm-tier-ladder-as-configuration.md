# ADR-0035: The GRM tier ladder is configuration, and it decides who may hold a case

- **Status**: Accepted
- **Date**: 25 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, GRM Lead (MGLSD), Engineering Lead
- **References**: ADR-0026 (ABAC multi-level scope); ADR-0028 (role catalogue); SAD §5.1 (Grievance entity), §4.4 (update routing matrix); UPD-O-01 / `apps.update_workflow.models.UpdRoutingRule`; `apps/grievance/assignees.py`, `apps/grievance/visibility.py`

---

## Context

A grievance has four tiers. The SAD names them and who owns each one:
"tier (L1 Parish Chief / L2 CDO / L3 District / L4 NSR Unit)" (§5.1),
with §4.4 confirming the two district-level ones — "L3 District M&E
sign-off", "NSR Unit Coordinator dual approval".

None of that reached the code as data.

The **SLA window** was a module constant in `services.py`:
24 / 48 / 72 / 168 hours, four numbers in a dict. The **role that owns
a tier** existed only inside the `Tier` enum's own value strings —
`"l2_cdo"` is a role name spelled into an identifier, which nothing
can read as configuration.

That was tolerable while nothing consulted it. Then assignment had to.

QA found that the console's assignee picker searched
`/api/v1/security/users/`: the entire user directory, active accounts
and deactivated ones alike, with no regard for what the case needed. An
L3 District grievance could be assigned to an enumerator in another
sub-region — someone with neither the authority to decide it nor the
geographic scope to open it. They would receive the assignment email,
follow the link, and be refused their own work by the registry's
ordinary ABAC check. The grievance would sit with a named owner who
could not see it.

Fixing the picker alone would have been a convenience. The rule had to
live at the service boundary, and a rule needs something to read.

## Decision

**1. `GrmTierRule` holds the ladder.** One active row per tier, giving
`required_role` (a code from the ADR-0028 catalogue) and `sla_hours`.
Seeded from the SAD by migration `grievance.0009`, which records for
each row the paragraph it came from. Same shape and the same reasoning
as `UpdRoutingRule` (UPD-O-01): rebalancing the ladder is an operations
decision, and policy that needs a deploy to change is policy operations
cannot see.

**2. No code fallback.** An unconfigured tier raises. `UpdRoutingRule`
originally fell back to a `DEFAULT_MATRIX` constant, which meant a
half-configured ladder silently reverted to whatever the constant last
said — the failure mode that let the hardcoded copy go unnoticed for
as long as it did. A missing row is an error, not a default.

**3. Two conditions decide who may be given a case**, applied in
`apps/grievance/assignees.py` and enforced by `assign()` and
`create_task()`, not only offered by the picker:

- **role** — the tier's `required_role`;
- **scope** — their `OperatorScope` must cover the household, checked
  with `user_can_access_household`, the same helper the household
  detail views enforce with.

**4. Queue-wide roles are exempt from the role condition.** `nsr_admin`
and `GRM Officer` already see and act on every case
(`visibility.sees_every_grievance`). A rule that let them read a case
but not be given it would be a second visibility vocabulary, which is
the defect `visibility.py` was written to remove.

**5. A grievance about no household is not decided by geography.** The
scope condition does not apply to it — exactly as
`visible_grievances` treats the same rows.

**6. The picker asks the case.** `GET /grm/grievances/{id}/assignable/`
returns the candidates, behind `get_object()` so it inherits the case's
visibility rule. The console renders what that returns. Because the
endpoint and the guard call the same predicate, the list can never
contain a name that `/assign/` would refuse — pinned by a test that
assigns every name the picker offers.

## Consequences

**A task cannot be created across a scope boundary any more.**
`visibility.py` grants sight of a grievance to whoever holds an open
task on it, and its docstring explains that this exists so "an operator
assigned a case outside their own area could not open the thing they
were told to work on". Going forward such an assignment is refused at
creation. The visibility grant stays: the registry has been assigning
tasks since US-S21 with no scope check, and those rows exist.

**The remediation command depends on the target being eligible.**
`remediate_phantom_assignees` moves cases onto a real account through
`assign()`, so that account must now clear the rule. On production it
is an `nsr_admin` with a national scope, which it does.

**Bulk assignment across a mixed selection has no single candidate
list.** Cases at different tiers or about different households cannot
share one. The console says so rather than offering a list it cannot
compute; each assignment is checked on submit.

**The escalation ORDER is still in code.** `escalate()` holds
L1→L2→L3→L4 as a literal map. That is structural rather than tunable —
it is the enum's own order — so it stays where it is. If operations
ever need to skip a tier, it belongs in this table and this ADR should
be revisited.

**Deactivating a user does not reassign their cases.** The rule is
checked when an assignment is made, not continuously. A case held by an
account that is later deactivated or moved keeps its `assigned_to`
until someone reassigns it. Surfacing those is not built; raised as an
open item.
