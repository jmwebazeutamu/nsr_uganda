# ADR-0040: One vocabulary for DSA field groups

- **Status**: Accepted
- **Date**: 25 September 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: Registry owner (jmwebaze), DSA owner (NSR Unit), Data Protection Officer, Engineering Lead
- **References**: ADR-0013 (canonical Partner/DSA models); ADR-0016 (DSA scope edit and renewal); `apps/data_requests/field_groups.py`, `apps/data_requests/builder_schema.py`

---

## Context

A Data Sharing Agreement grants a partner access by **group** —
`field_scope = {"Identifiers": true, "PMT": true}`. A data request
names **field paths** — `household.sub_region_code`.
`builder_schema.FIELD_CATALOGUE` is the only maintained mapping between
the two, so `_requested_field_groups` resolves a request through it.

The groups themselves were listed in three places, and the three
disagreed:

| Concept | Catalogue (enforced) | Console (written) |
|---|---|---|
| Household roster | `Members` | `Roster` |
| Dwelling + utilities | `Dwelling`, `Utilities` | `Housing` |
| Food scores | `Food consumption`, `Food security` | `FoodShocks` |
| Location | `Geography` | **not offered at all** |

So an agreement written in the console granted `Roster`; a partner
asked for `member.surname`; the validator resolved it to `Members`, did
not find it in the grant, and refused the request as **"outside DSA
scope"** — for a group the agreement did grant, in wording that blames
the partner for asking.

And because `Geography` was never on the console's list, **no agreement
created through the UI could grant a partner the household's
location**. That is what the end-to-end DRS test had been failing on
since the scope check moved from model prefixes to catalogue groups.

Two agreements in production were written in the old vocabulary
(`DSA_OPM_Johnson Mwebaze`, `kkk`). Neither was active, so no partner
had yet been refused — that is luck, not a control.

## Decision

**`apps/data_requests/field_groups.py` is the vocabulary**, derived
from `FIELD_CATALOGUE` rather than listed again. It carries the
operator-facing description of each group, the legacy aliases, and the
normalisation.

**The console asks for it** — `GET /api/v1/drs/requests/field-groups/`,
read by `v0.1/data/use-field-groups.jsx`. Both scope pickers lost their
lists.

**A picker that cannot reach the API renders no checkboxes**, with an
error, rather than a plausible-looking fallback. A scope picker quietly
offering the wrong vocabulary is exactly how the two production
agreements came to be written; a fallback list would reintroduce the
defect at the moment it matters most.

**Legacy names expand rather than rename.** `Housing` covered two
catalogue groups and `FoodShocks` covered two; migration
`partners.0013` maps them to both. Narrowing a signed agreement is not
a migration's decision — if the expansion is wider than the DSA owner
intended, that is an amendment for them to make deliberately, and the
DPO should see it.

**A group nothing can resolve is dropped**, because a grant nothing can
look up authorises nothing, and keeping it makes the agreement read
wider than it is.

## Consequences

**Grantable scope widens for anyone using the console.** `Geography`,
`Livelihood`, `Lifecycle`, `Programmes`, `Dwelling`, `Utilities`,
`Food consumption` and `Food security` were never offered and now are.
That is the fix, and it is also a disclosure surface the DSA owner and
the DPO should look at before the next agreement is signed: the picker
now offers eight things it did not offer last week.

**`Shock` has no group.** The console's `FoodShocks` label promised
"FCS, FIES, shock history", and the catalogue carries no shock fields
at all. Shock history cannot be granted because it cannot be requested.
Flagged rather than invented — adding it means adding the fields to
`FIELD_CATALOGUE`, which is a disclosure decision, not a rename.

**`FIELD_CATALOGUE` is still a hardcoded list in application code**,
which the project's own rules forbid for lookup vocabularies. It
survives here because the alternative is worse: the Questionnaire
Authoring dictionary's `section` (Identification, Roster, Health) is a
*questionnaire* axis, and the DSA group is a *disclosure* axis. They
are not the same classification and collapsing them would give
partners access by accident of form layout.

The honest position is that **the disclosure classification is a
missing schema dependency**. Until the Schema Registry carries one,
`FIELD_CATALOGUE` is the registry for it and `field_groups.py` is the
single way everything else reads it — one copy instead of three, which
is the improvement available today.
