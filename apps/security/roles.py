"""The role catalogue — one definition, three consumers (US-063, ADR-0006).

Before this module there were three overlapping lists and no crosswalk:

* **US-063 (the TOR)** — 18 named roles and 8 named permissions, the
  contractual requirement, none of it implemented.
* **ADR-0006** — 9 Keycloak realm roles, each with a scope level.
* **The database** — 8 Django Groups (`nsr_admin`, `GRM Officer`, `EXPLORER`,
  `nsr_dba`, `dpo`, `nsr_security`, `mglsd_statistics`,
  `nsr_unit_coordinator`), used as bare name checks and carrying **zero**
  permissions.

Three lists that must agree, maintained by hand, is the same failure mode that
put Epic 17 five stories out of date. So the catalogue lives here once and
everything else is derived:

* `sync_groups()` materialises Django Groups + their permissions (called from
  a migration, and re-runnable as `manage.py sync_roles`).
* `security.E002` asserts the Keycloak realm JSON declares exactly these
  role codes, so the realm and the app cannot drift apart.

## Naming

`code` is *both* the Django Group name and the Keycloak realm role. Where a
Group already existed its name is kept verbatim — including the inconsistent
`GRM Officer` and `EXPLORER` — because live authorisation checks compare
against those exact strings (`apps/grievance/api.py`,
`apps/security/impersonation.py`, `apps/admin_console/refdata_api.py`).
Renaming them would silently disable those checks, which is precisely the
class of defect this work exists to prevent. The inconsistency is recorded as
debt in ADR-0028 rather than fixed under an authorisation change.

## Permissions

The eight TOR actions are cross-cutting, not per-model, so they are anchored
on `AccessPolicy` — a table-less-by-intent model whose only job is to give
them a ContentType. Check them as `user.has_perm("security.data_approve")`.

**The role → permission matrix below is a defensible default, not a signed-off
one.** It needs MGLSD confirmation; see ADR-0028 §"Open".
"""

from __future__ import annotations

from dataclasses import dataclass

# --- the eight TOR permissions ---------------------------------------------

DATA_VIEW = "data_view"
DATA_ENTRY = "data_entry"
DATA_MODIFY = "data_modify"
DATA_DELETE = "data_delete"
DATA_APPROVE = "data_approve"
DATA_EXPORT = "data_export"
DATA_DOWNLOAD = "data_download"
DATA_UPLOAD = "data_upload"

PERMISSIONS: dict[str, str] = {
    DATA_VIEW: "Data View — read personal data within scope",
    DATA_ENTRY: "Data Entry — create new records",
    DATA_MODIFY: "Data Modifier — amend existing records",
    DATA_DELETE: "Data Deletion — soft-delete records",
    DATA_APPROVE: "Data Approval — approve a change raised by someone else",
    DATA_EXPORT: "Data Export — generate an extract",
    DATA_DOWNLOAD: "Data Download — retrieve a generated extract",
    DATA_UPLOAD: "Data Upload — bulk-import a dataset",
}

# Scope levels — mirrors apps.security.models.ScopeLevel. Duplicated as plain
# strings so this module stays importable from migrations without touching the
# model layer.
NATIONAL = "national"
DISTRICT = "district"
SUB_COUNTY = "sub_county"
PARISH = "parish"
PARTNER = "partner"


@dataclass(frozen=True)
class Role:
    code: str
    label: str
    permissions: frozenset[str]
    default_scope: str
    #: The ADR-0006 realm role this corresponds to, where one exists.
    adr0006: str | None = None
    #: True for partner-affiliated (external) roles — scope_code is a
    #: Partner.code rather than a geographic code.
    external: bool = False
    #: False for roles that exist operationally but are not in the TOR's 18.
    in_tor: bool = True
    notes: str = ""


def _r(code, label, perms, scope, **kw) -> Role:
    return Role(code=code, label=label, permissions=frozenset(perms),
                default_scope=scope, **kw)


_ALL = frozenset(PERMISSIONS)
_READ = (DATA_VIEW,)
_READ_OUT = (DATA_VIEW, DATA_EXPORT, DATA_DOWNLOAD)
_CAPTURE = (DATA_VIEW, DATA_ENTRY)
_CAPTURE_EDIT = (DATA_VIEW, DATA_ENTRY, DATA_MODIFY)
_REVIEW = (DATA_VIEW, DATA_ENTRY, DATA_MODIFY, DATA_APPROVE)


ROLES: tuple[Role, ...] = (
    # --- the TOR's 18 -------------------------------------------------------
    _r("nsr_admin", "Super Admin", _ALL, NATIONAL, adr0006="SA",
       notes="Pre-existing group; gates impersonation + OperatorScope admin."),
    _r("nsr_unit_coordinator", "SR Coordinator",
       (DATA_VIEW, DATA_APPROVE, DATA_EXPORT, DATA_DOWNLOAD), NATIONAL,
       adr0006="NSR_UNIT_COORDINATOR"),
    _r("mis_specialist", "MIS Specialist",
       (DATA_VIEW, DATA_ENTRY, DATA_MODIFY, DATA_EXPORT, DATA_DOWNLOAD,
        DATA_UPLOAD), NATIONAL),
    _r("systems_architect", "Systems Architect", _READ, NATIONAL),
    _r("application_developer", "Application Developer", _READ, NATIONAL,
       notes="Read-only in production; no data actions."),
    _r("nsr_dba", "DBA", (DATA_VIEW, DATA_DELETE, DATA_EXPORT, DATA_DOWNLOAD),
       NATIONAL, notes="Pre-existing group; gates reference-data admin."),
    _r("EXPLORER", "Data Analyst", _READ_OUT, NATIONAL,
       notes="Pre-existing group; gates the Data Explorer surface."),
    _r("m_and_e_officer", "M&E Officer", _READ_OUT, DISTRICT,
       adr0006="DISTRICT_M_AND_E"),
    _r("GRM Officer", "Grievance Officer", _CAPTURE_EDIT, NATIONAL,
       notes="Pre-existing group. GRM visibility is group-gated, not "
             "geographic — see apps/grievance/api.py."),
    _r("communications_officer", "Communications Officer", _READ, NATIONAL),
    _r("admin_officer", "Admin Officer", _CAPTURE, DISTRICT),
    _r("programme_manager", "Programme Manager (external)",
       (DATA_VIEW, DATA_EXPORT, DATA_DOWNLOAD), PARTNER,
       adr0006="PARTNER_ANALYST", external=True,
       notes="Raises DataRequests under a DSA (Data Export) and collects the "
             "resulting bundle (Data Download). No write access to the registry."),
    _r("programme_caseworker", "Programme Caseworker (external)", _READ,
       PARTNER, external=True),
    _r("parish_chief", "Parish Chief", _CAPTURE_EDIT, PARISH,
       adr0006="PARISH_CHIEF"),
    _r("cdo", "CDO", _REVIEW, DISTRICT, adr0006="CDO"),
    _r("enumerator", "Enumerator", _CAPTURE, PARISH,
       adr0006="FIELD_ENUMERATOR"),
    _r("supervisor", "Supervisor", _REVIEW, SUB_COUNTY),
    _r("auditor", "Auditor", _READ_OUT, NATIONAL,
       notes="Reads the audit chain across geographies; never writes."),

    # --- operational roles that predate the TOR list ------------------------
    _r("dpo", "Data Protection Officer", _READ_OUT, NATIONAL, adr0006="DPO",
       in_tor=False,
       notes="Reads across all geographies for DPIA work; must not write."),
    _r("nsr_security", "Security Officer", _READ_OUT, NATIONAL, in_tor=False,
       notes="Incident response (US-067)."),
    _r("mglsd_statistics", "MGLSD Statistics", _READ_OUT, NATIONAL,
       in_tor=False),
    _r("partner_dpo", "Partner DPO (external)", _READ_OUT, PARTNER,
       adr0006="PARTNER_DPO", external=True, in_tor=False,
       notes="Read-only across the partner's own data."),
)

BY_CODE: dict[str, Role] = {r.code: r for r in ROLES}
ROLE_CODES: frozenset[str] = frozenset(BY_CODE)

#: ADR-0006 realm role -> our role code. Both directions are needed: the realm
#: emits ADR-0006 names in `realm_access.roles`, and Phase 1 maps them here.
ADR0006_TO_CODE: dict[str, str] = {
    r.adr0006: r.code for r in ROLES if r.adr0006
}


def permissions_for(code: str) -> frozenset[str]:
    role = BY_CODE.get(code)
    return role.permissions if role else frozenset()


def sync_groups(apps=None) -> dict[str, int]:
    """Create/refresh a Django Group per role and attach its permissions.

    Idempotent. `apps` is the migration registry when called from a data
    migration, otherwise the live registry is used.

    Additive by design: a Group not in the catalogue is left alone rather than
    deleted, because removing a group silently removes access and some groups
    may be created operationally.
    """
    if apps is None:
        from django.apps import apps as _apps
        apps = _apps

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct, _ = ContentType.objects.get_or_create(
        app_label="security", model="accesspolicy",
    )
    perms: dict[str, object] = {}
    for codename, name in PERMISSIONS.items():
        p, _ = Permission.objects.get_or_create(
            content_type=ct, codename=codename, defaults={"name": name},
        )
        if p.name != name:
            p.name = name
            p.save(update_fields=["name"])
        perms[codename] = p

    created = 0
    for role in ROLES:
        group, was_created = Group.objects.get_or_create(name=role.code)
        created += int(was_created)
        group.permissions.set([perms[c] for c in sorted(role.permissions)])

    return {"roles": len(ROLES), "groups_created": created,
            "permissions": len(PERMISSIONS)}
