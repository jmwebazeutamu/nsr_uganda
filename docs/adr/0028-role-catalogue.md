# ADR-0028: One role catalogue — reconciling US-063, ADR-0006 and the Django Groups

- **Status**: Accepted
- **Date**: 9 August 2026
- **Owner**: NSR MIS Architecture Team
- **Decision-makers**: NSR Unit Coordinator, Data Protection Officer, Engineering Lead
- **References**: US-063 (RBAC, Must), US-064 (account hygiene), SAD §8.2; ADR-0006 (Keycloak realm design); ADR-0026 (multi-level ABAC scope); `docs/keycloak_oidc_scope.md` §2.2; `apps/security/roles.py`

---

## Context

Three overlapping role lists existed, with no crosswalk between them:

| source | contents | implemented |
|---|---|---|
| **US-063 (the TOR)** | 18 named roles, 8 named permissions | no |
| **ADR-0006** | 9 Keycloak realm roles, each with a scope level | realm only |
| **The database** | 8 Django Groups, **zero permissions** | yes, as bare name checks |

US-063 was nonetheless marked *Done* in the sprint plan — the same
over-statement pattern the 2026-08-08 audit found on Epic 17.

The Groups were doing real work despite carrying no permissions: code compares
`user.groups.filter(name="nsr_admin")`, `name="GRM Officer"`, `"EXPLORER"`,
`"nsr_dba"` by exact string. So "roles" existed as membership, but the eight
TOR *permissions* did not exist at all, and nothing connected either to the
realm that Phase 1 will provision from.

Keeping three hand-maintained lists in agreement is precisely what put the
sprint plan five stories out of date.

## Decision

### D1. One catalogue, in code, with everything else derived.

`apps/security/roles.py` is the single definition: role code, label, permission
set, default `ScopeLevel`, external flag, and the ADR-0006 crosswalk. From it:

- `sync_groups()` materialises Django Groups and attaches permissions —
  invoked by migration `security.0006`, re-runnable as `manage.py sync_roles`.
- The Keycloak realm role list is generated from it.
- `security.E005` fails `manage.py check` if the realm export and the catalogue
  disagree.

### D2. The realm role code *is* the Django Group name.

Rather than translate ADR-0006's `PARISH_CHIEF` into a group named
`parish_chief` at login, the realm declares `parish_chief` directly. A
`realm_access.roles` entry maps 1:1 onto a Group, so Phase 1 has a lookup, not
a translation table — one fewer place to drift.

ADR-0006's names survive in the catalogue's `adr0006` field as documentation of
the crosswalk.

### D3. Pre-existing Group names are kept verbatim, including the ugly ones.

`GRM Officer` (space, title case) and `EXPLORER` (upper case) sit beside
`nsr_admin` and `parish_chief`. That inconsistency is deliberate: those exact
strings are compared in live authorisation checks, and renaming them would
silently disable the check rather than fail loudly. Renaming is a separate
change with its own tests, not a side effect of an authorisation refactor.

### D4. The eight TOR permissions are cross-cutting, anchored on `AccessPolicy`.

"Data Approval" is not a property of any one table — it spans DAT, UPD, DDUP
and DIH. Rather than scatter eight near-duplicate permissions across every
model, they are declared once on `apps.security.AccessPolicy`, a deliberately
empty model whose only job is to give them a ContentType, with
`default_permissions = ()` so Django's add/change/delete/view quartet is not
generated. Check them as `user.has_perm("security.data_approve")`.

### D5. Sync is additive.

A Group not in the catalogue is left alone, never deleted. Removing a group
removes access, and some groups are created operationally; a `migrate` should
not silently strip access from live accounts. Reversing the migration drops the
permissions it created but keeps the Groups, for the same reason.

### D6. The catalogue is a superset of the TOR's 18.

Four operational roles predate the TOR list and remain, flagged `in_tor=False`:
`dpo`, `nsr_security`, `mglsd_statistics`, `partner_dpo`. 22 roles in total.

## Consequences

**Good.** US-063's roles and permissions exist for the first time, and
`has_perm` works. Phase 1 of the Keycloak work has a role vocabulary to map
onto with no ambiguity. Drift between the realm and the app is now a build
failure rather than a silent grant.

**Good.** Adding a role is a single edit plus a `sync_roles` run; the realm
list and checks follow.

**Cost.** Group names are stylistically inconsistent (D3). Recorded as debt.

**Cost.** 22 groups where there were 8. Most have no members yet — they exist
so membership can be granted rather than invented per deployment.

**Not addressed here.** The permissions are *declared and assigned*; they are
not yet *enforced* at the viewset layer. Every endpoint still authorises via
`IsAuthenticated` plus ABAC geographic scope. Wiring `has_perm` into
`permission_classes` is deliberate follow-on work — doing it in the same change
as introducing the catalogue would have made a large, hard-to-review
authorisation diff.

## Open

- **The role → permission matrix is a defensible default, not a signed-off
  one.** It was derived from role titles, not from an MGLSD statement of who
  may do what. `manage.py sync_roles --dry-run` prints it for review. **It
  needs MGLSD sign-off before pilot.**
- **Segregation of duties** ("data entry cannot approve own record", US-063) is
  already enforced at record level by `AC-UPD-NO-SELF-APPROVE`, and is only
  meaningful now that the acting identity comes from the session rather than
  the request body (2026-08-08). No role in the catalogue is barred from
  holding both `data_entry` and `data_approve`, because supervisors legitimately
  do both — just not on the same record.
- **US-064 account hygiene** (password rotation, lockout, inactivity disable,
  MFA, CAPTCHA) is Keycloak realm configuration, not code. Brute-force
  protection is already on in the dev realm; the rest lands with Phase 3.

## Alternatives considered

**Adopt ADR-0006's 9 roles and treat US-063's 18 as aspirational.** Rejected:
US-063 is a Must with contractual force, and the 9 have no home for
MIS Specialist, DBA, Auditor and the rest.

**Rename the legacy groups to a consistent scheme.** Rejected for now — see D3.
The rename is safe only with the permission checks in place to fail loudly, so
it should follow, not precede.

**Per-model Django permissions instead of the eight cross-cutting ones.**
Rejected: the TOR names eight action classes, not per-table CRUD, and mapping
"Data Approval" onto `change_changerequest` loses the meaning the auditor is
looking for.
