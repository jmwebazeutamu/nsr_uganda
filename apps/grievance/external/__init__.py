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

#: The registered `ingestion_hub.SourceSystem` this partner's records
#: arrive under. Registering the source is what gives the pull an
#: agreement register, a run record and a landing table; it does NOT
#: put grievances through DIH's staging pipeline. See ADR-0044.
SOURCE_CODE = "STAAC_GRM"
CONNECTOR_NAME = "staac-partner-api"

#: The registered source a grievance opened in this registry's own
#: console carries. Registered like any other source so the console
#: can name it without inventing a label — see migration
#: grievance.0018.
WEB_SOURCE_CODE = "NSR-WEB"
