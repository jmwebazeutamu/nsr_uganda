"""Receiving grievances from STAAC's GRM over the partner API.

The contract is `docs/NSR_STAAC_GRM_API_SPECIFICATION_v1.md` in the
STAAC repository: a cursor-paged collection of approved handovers and
an immutable snapshot per handover. Read-only from this registry's
side — NSR may not close a STAAC case, report an outcome back, or
search STAAC by tracking number.

`client` speaks HTTP and knows nothing about grievances. `service`
turns a snapshot into a Grievance and knows nothing about HTTP. The
split is what lets the whole pull be tested against a mocked partner.
"""

#: Who the audit chain records for a pull. One definition: it was
#: three independent default arguments, and three defaults agreeing is
#: not the same as one fact.
PULL_ACTOR = "staac-pull"
