# Roles & scopes — ABAC model audit

**Date:** 2026-08-09
**Commit:** `f7605f9`
**Question asked:** does the roles-and-scopes model implement *full* ABAC?
**Short answer:** it implements a solid **two-attribute** ABAC — subject role and
subject geography — enforced consistently and failing closed. Four attribute
classes that "full ABAC" implies are **absent**, and one of them (consent) is
directly relevant to DPPA 2019.

---

## 1. What is genuinely implemented

| ABAC element | Status | Where |
|---|---|---|
| **Subject: role** | ✅ 22 roles, carrying 8 TOR permissions | `apps/security/roles.py` (ADR-0028) |
| **Subject: geography** | ✅ 7 levels — national → village | `OperatorScope`, `ScopeLevel` |
| **Subject: partner affiliation** | ✅ `PARTNER` scope, `scope_code = Partner.code` | ADR-0026 |
| **Action** | ✅ 8 TOR actions, enforced on writes | `HasDataPermission` |
| **Resource: geography** | ✅ Household's denormalised FK ladder | `apps/security/abac.py` |
| **Policy enforcement point** | ✅ 5 queryset mixins + 2 single-entity helpers, 13 modules | `ScopedQuerysetMixin` etc. |
| **Fail-closed default** | ✅ no scope → zero rows | verified below |
| **Non-disclosure on denial** | ✅ out-of-scope returns empty, not 404 | so existence is not confirmed |

Verified end-to-end during this audit with a real operator:

```
demo-chief — role parish_chief, scope parish=411.05.05.04
  households visible : 3 of 284          <- geography attribute
  POST grievance     : 400, not 403      <- role carries data_entry
  /admin-console/    : 403               <- role gate
```

Two attributes, combined, produce the right answer. That is real ABAC — just
not *complete* ABAC.

---

## 2. Gaps against "full ABAC"

### G1 — Consent is not an access attribute *(highest value)*

`apps/security/abac.py` contains **zero** references to consent. The consent
module (Epic 19, 17 stories, `apps/consent/`) records purpose-scoped consent
and withdrawal with a 30-day SLA — and none of it constrains a read.

A household that has withdrawn consent for, say, `RESEARCH` is today just as
visible to an analyst as one that has not. The withdrawal is recorded,
audited, and has no effect at the point of access.

For a registry governed by DPPA 2019 this is the gap that matters most: consent
state is the canonical example of an attribute an ABAC policy should consult.

### G2 — No purpose limitation

US-014 ("Restricted fields require role + purpose justification") is *Not
started*. Nothing captures **why** an operator is accessing a record, so no
policy can condition on it and the audit trail cannot record it. Purpose is the
attribute that distinguishes ABAC from role-scoped RBAC, and it is absent.

### G3 — Sensitivity is not a registry-wide attribute

`PrivacyClass` exists and is used properly — but only inside
`apps/data_explorer/`. It classifies *datasets* for aggregate queries. There is
no sensitivity attribute on Household/Member fields that the registry-wide
policy can read, so "this operator may see health data, that one may not" is
not expressible.

### G4 — No environment attributes

No condition on time of day, source network, device, or session risk. A
Parish Chief's credential works identically at 03:00 from an unknown IP as at
noon from the district office.

### G5 — Scopes have no validity window

`OperatorScope` has `active`, `granted_at`, `granted_by`, `note` — but **no
`expires_at`**. A secondment, an emergency elevation or a contractor's access
cannot be time-boxed; it is revoked only when someone remembers to flip
`active`. ADR-0006 already flags the related question of stale scopes after a
role is dropped, as an open **DPO action**.

### G6 — Field-level control is static, not attribute-based

`nin_value` is serialised as `None` for *everyone* — a safe blanket rule,
and the right default. But it is not attribute-driven: there is no mechanism
by which a DPO or an identity-verification officer could be granted the
plaintext where an enumerator is not. Any future "role X may see field Y"
requirement has nowhere to attach.

### G7 — Assigning a role grants no scope

The catalogue records a `default_scope` per role, and it is **documentation
only** — nothing applies it. Create a user, give them `cdo`, and they see
nothing until someone separately creates an OperatorScope. The mixins fail
closed, so the symptom is an empty screen, not an error.

This is the single most likely operational mistake in the current model, and
it is now mitigated (§3) rather than fixed at the model level.

### G8 — Policy is code, not data

Authorisation lives in Python mixins. That is legible and testable, but there
is no policy catalogue to review as data, no explicit deny rules, and no
combination/precedence model — everything is allow-by-scope. An auditor asking
"show me every rule that governs Member reads" must read source.

### G9 — Reads are not action-gated *(deliberate)*

`HasDataPermission` gates writes and extracts only. Recorded here so it is a
visible decision rather than an oversight: enforcing Data View as well took the
suite from 3 failures to 103, every one a correctly-scoped operator without a
group, and reads are already bounded by `IsAuthenticated` + ABAC — the
mechanism SAD §8.2 actually names.

---

## 3. Creating users and assigning roles / permissions / attributes

Previously this meant two disconnected admin screens plus the knowledge that a
role without a scope is blind. Now:

### Django admin — `/admin/auth/user/`

The stock user admin is replaced by an operator-aware one
(`apps.security.admin.OperatorAdmin`):

* **ABAC scopes inline** on the user page — account, role and attribute in one
  place;
* **"Permissions carried by these roles"** — the effective TOR permissions,
  computed from the catalogue;
* **"Scope expected for these roles"** — the `default_scope` guidance, so G7 is
  visible at the moment it matters;
* **"Can see data?"** column on the changelist — flags accounts missing a role
  or a scope, which otherwise present as an empty screen.

### Command line — one step, with guardrails

```
manage.py create_operator alice --role parish_chief --scope-code KLA-CEN
manage.py create_operator bob   --role nsr_unit_coordinator
manage.py create_operator carol --role programme_manager --scope-code PDM
manage.py sync_roles --dry-run      # print the role → permission matrix
```

It refuses the combinations that produce a blind account: a scoped role with no
`--scope-code`, a `--scope-code` on national, an unknown role, or a role whose
Group has not been synced. Passwords are never taken as arguments — they would
be captured in shell history and visible in `ps` — so the account is created
with an unusable password and set via `changepassword`.

---

## 4. Recommended order

1. **G1 consent-as-attribute.** Highest compliance value, and the consent data
   already exists — it is a matter of joining it at the policy point.
2. **G7 role → default scope.** Cheap; apply the catalogue's `default_scope`
   when a role is granted. Also removes work from Keycloak Phase 1, which will
   otherwise have to do it from claims.
3. **G5 `expires_at` on OperatorScope.** Small migration, closes the
   time-boxing gap and gives the DPO's stale-scope question a mechanism.
4. **G2 purpose limitation** (US-014) — larger, needs DPO input on the purpose
   vocabulary.
5. G3/G4/G6/G8 — architectural, worth an ADR before building.

## Method

Read `apps/security/{abac,roles,permissions,models}.py`, the five scope mixins
and their call sites, `apps/data_management/api.py` (field exposure),
`apps/consent/`, `apps/data_explorer/` (PrivacyClass); grepped for
cross-references; and exercised a live operator against the running stack.

One correction made during the audit: an initial `POST` test returned 403 and
looked like a permission denial. It was a missing CSRF token. Re-tested with
the token: 400, i.e. the permission layer had allowed it. Worth noting because
403-from-CSRF and 403-from-permission are easy to confuse when testing
authorisation by hand.
