# ADR-0036: A closed grievance is read-only

- **Status**: Accepted
- **Date**: 25 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: Registry owner (jmwebaze), GRM Lead (MGLSD), Engineering Lead
- **References**: ADR-0029 (audit chain, append-only); ADR-0035 (GRM tier ladder); SAD §4.5, §5.1, §8.4; `apps/grievance/services.py` (`_require_open_for_writing`), `apps/grievance/visibility.py` (`allowed_actions`)

---

## Context

Every GRM *transition* already refused a closed case. Assign, escalate,
resolve and close all check the status, and the SLA sweep and the
UPD-commit signal both exclude CLOSED.

Three things still wrote to one.

**A note could be appended to the thread.** This was deliberate, and
the reasoning was written down: "a comment records what someone knew or
did; refusing to store it because the case has moved on loses the
record rather than protecting anything."

**A linked ChangeRequest could be opened from it.**
`open_change_request_for_grievance` checked the category, the subject
and whether a CR already existed — not the status. It then wrote
`linked_change_request_id` onto the closed row, which is a field change
on a settled record.

**A task could in principle be moved.** Not reachable through the
normal lifecycle — a case cannot resolve with an open task, and close
requires resolved — but nothing said so.

So a closed grievance was closed for the state machine and open for
everything else.

## Decision

A closed grievance is read-only. `services._require_open_for_writing`
is the rule, called by `add_comment`, `open_change_request_for_grievance`
and `transition_task`; `allowed_actions` returns `[]` for a closed
case, so the console offers nothing rather than offering something the
server will refuse.

The comment-thread reasoning is sound for a case still being worked and
wrong for a settled one. The closing narrative is meant to be the last
word on what happened. A thread that keeps growing after it means the
record of a closed case is not actually closed, and an auditor reading
the case cannot tell which parts were the basis of the closure and
which arrived afterwards. **New information about a closed case is a new
case.**

**Resolved is not closed.** A resolved case still accepts notes and
still shows Close. The grace period before closure is exactly when a
reporter calls back, and that has to land somewhere.

**The rule lives in one function**, not at each caller, so that adding
a fourth writer does not quietly reopen the hole.

**The audit chain is exempt, by design.** It is append-only (ADR-0029)
and records *access and operations*, not the case's own content.
Writing an event about a closed grievance does not change the
grievance. This matters concretely: `remediate_phantom_assignees`
annotates historical demo records with what they are, and for a closed
one that annotation now goes to the chain under action
`grm.provenance_note` rather than to the thread. A record with a
phantom assignee and nothing saying why is what that command exists to
prevent, and the chain is where "this is what this historical row is"
belongs anyway.

## Consequences

**A closed case is permanently frozen, because there is no reopen.**
This is the consequence to be aware of. The SAD does not mention
re-opening a grievance at all — not permitted, not forbidden, absent —
and `allowed_actions` deliberately omits it (see the note in
`visibility.py`): turning a closed, audited case back into a live one
raises questions the architecture has not answered, about whether the
SLA clock restarts, whether it needs approval, and whether the reporter
is told. Combined with this ADR, a closed case can never change again
by any route. If that is too strict in practice, the answer is a
designed reopen transition, not a hole in this rule.

**"Open a linked update" is also withheld once one exists.** The
service already refused a second ChangeRequest; `allowed_actions` now
says so, because offering a button that only ever errors is the same
defect in a smaller frame.

**The console shows why, not just less.** The note composer is
replaced by a line saying the case is closed and to raise a new
grievance — a box you can type a paragraph into and lose is worse than
no box.

**Existing data is untouched.** Comments already on closed cases stay;
this changes what can be added, not what is there. One such comment
exists in production, written by the phantom-assignee remediation on
19 September 2026.
