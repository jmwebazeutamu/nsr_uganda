"""Apply the role catalogue's `default_scope` when a role is granted (G7).

Until now `default_scope` was documentation. Adding someone to `cdo` gave them
the CDO permissions and **no OperatorScope**, and because the ABAC mixins fail
closed the symptom was an empty screen rather than an error — the likeliest
operational mistake in the model (2026-08-09 ABAC audit, G7).

The fix is deliberately asymmetric, because the two cases are not alike:

* **national roles are fully determined.** `OperatorScope(NATIONAL, "")` is the
  whole grant; there is nothing left to choose, so it is created automatically.
  This is also exactly what ADR-0006 specifies for Keycloak Phase 1 ("if the
  role implies NATIONAL scope, ensure an active OperatorScope row exists"), so
  doing it here means Phase 1 inherits it rather than reimplementing it.

* **geographic and partner roles are not.** `district` needs *which* district;
  `partner` needs *which* partner. There is no safe default: an empty
  `scope_code` at a non-national level matches nothing, so auto-creating one
  would swap a visible "no scope" for an invisible "scope that matches
  nothing" — strictly worse. Those are reported, never invented.

Granting national visibility over the whole registry is a significant act, so
it emits an AuditEvent rather than happening silently.

Removal is deliberately NOT handled: dropping a role does not deactivate the
scope. ADR-0006 leaves that open as a **DPO action** (recommending a daily
sweep rather than immediate deactivation), and quietly revoking access on a
group edit would pre-empt that decision. `audit_operator_scopes` reports the
orphans instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.security import roles as role_catalogue

NATIONAL = "national"


@dataclass
class ScopeProvisionResult:
    granted: list[str] = field(default_factory=list)
    already_had: list[str] = field(default_factory=list)
    #: (role_code, level) pairs that need a human to supply a scope_code.
    needs_manual_scope: list[tuple[str, str]] = field(default_factory=list)

    @property
    def blind(self) -> bool:
        """True when the account holds roles but still cannot see any row."""
        return bool(self.needs_manual_scope) and not (self.granted or self.already_had)


def ensure_default_scopes(user, *, actor: str = "role-sync",
                          commit: bool = True) -> ScopeProvisionResult:
    """Create the OperatorScope rows a user's roles fully determine."""
    from apps.security.models import OperatorScope

    result = ScopeProvisionResult()
    codes = list(user.groups.values_list("name", flat=True))

    for code in sorted(codes):
        role = role_catalogue.BY_CODE.get(code)
        if role is None:
            continue  # a group outside the catalogue carries no scope contract

        if role.default_scope != NATIONAL:
            # Cannot be derived — needs the district/parish/partner code.
            if not OperatorScope.objects.effective().filter(
                user=user, scope_level=role.default_scope,
            ).exists():
                result.needs_manual_scope.append((role.code, role.default_scope))
            continue

        existing = OperatorScope.objects.filter(
            user=user, scope_level=NATIONAL,
        ).first()
        if existing is not None:
            if existing.active:
                result.already_had.append(role.code)
            continue

        if commit:
            OperatorScope.objects.create(
                user=user, scope_level=NATIONAL, scope_code="",
                active=True, granted_by=actor,
                note=f"auto-granted with role {role.code}",
            )
            # National scope is visibility over the entire registry. Loud, not
            # silent.
            from apps.security.audit import emit
            emit(
                "create", "operator_scope", f"{user.pk}:national",
                actor=actor,
                reason=f"national scope auto-granted with role {role.code}",
                field_changes={"scope_level": ["national", None],
                               "role": [role.code, None]},
            )
        result.granted.append(role.code)

    return result
