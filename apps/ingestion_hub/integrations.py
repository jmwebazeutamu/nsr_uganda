"""Every system this registry exchanges data with, described once.

A console screen that lists integrations has two possible shapes. It
can know, in JavaScript, that STAAC has a bearer token and Kobo has a
Knox token and UBOS has neither — in which case adding a connector
means editing a screen, and the screen's idea of what exists drifts
from the register's. Or the server can describe what it has and the
screen can render the description.

This is the description. The LIST comes from `SourceSystem`, which is
already the registry's answer to "which systems do we exchange with",
so an integration appears on the screen by being registered rather
than by someone remembering to add it. What is generic — is the
source registered, is there a connector, is an agreement in force,
what has it run — is computed here for every kind. What is specific
is an adapter, registered by the app that owns it, so GRM's partner
credential is described by GRM and DIH does not import it.

A kind with no adapter is not an error. UBOS, ODK, WFP SCOPE and the
walk-in channels appear with what is known about them and no actions,
which is the honest rendering of "registered, not wired yet" — and
better than being absent, because absent reads as "does not exist".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q

from .models import (
    Connector,
    ConnectorRun,
    DataProvisionAgreement,
    SourceSystem,
    SourceSystemKind,
)


@dataclass(frozen=True)
class Check:
    """One line of a readiness list: is it done, and what is it."""

    ok: bool
    label: str
    detail: str = ""


@dataclass
class Integration:
    """One system, and everything a screen needs to show about it."""

    code: str
    name: str
    kind: str
    kind_label: str
    description: str = ""
    is_active: bool = True
    #: Where the row came from, when we can say. The question that
    #: prompted this whole screen was "STAAC_GRM is under Connector
    #: runs — how did it get there".
    registered_by: str = ""
    connector: str = ""
    direction: str = "inbound"
    credential: dict = field(default_factory=dict)
    agreement: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    #: Endpoint per action, or absent. The screen renders a button for
    #: what is here and nothing for what is not, so an integration
    #: that cannot be triggered from the console simply has no button
    #: rather than one that 400s.
    actions: dict = field(default_factory=dict)
    runs: list = field(default_factory=list)
    #: Anything only this integration has. Rendered as labelled rows,
    #: so an adapter can add a fact without the screen learning it.
    extra: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "kind": self.kind,
            "kind_label": self.kind_label, "description": self.description,
            "is_active": self.is_active, "registered_by": self.registered_by,
            "connector": self.connector, "direction": self.direction,
            "credential": self.credential, "agreement": self.agreement,
            "checks": [
                {"ok": c.ok, "label": c.label, "detail": c.detail}
                for c in self.checks
            ],
            "blockers": self.blockers, "actions": self.actions,
            "runs": self.runs, "extra": self.extra,
        }


#: kind -> a function that fills in what only that kind knows.
_ADAPTERS: dict[str, Callable[[SourceSystem, Integration], None]] = {}


def register_adapter(kind: str):
    """Let the app that owns an integration describe it.

    Same shape as `connectors.register_connector`, for the same
    reason: the alternative is DIH importing every other app to
    learn what a credential looks like there.
    """

    def _wrap(fn):
        _ADAPTERS[kind] = fn
        return fn

    return _wrap


def _agreement_for(source: SourceSystem) -> dict:
    today = date.today()
    row = (
        DataProvisionAgreement.objects
        .filter(source_system=source, valid_from__lte=today)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .order_by("-valid_from")
        .first()
    )
    if row is None:
        held = DataProvisionAgreement.objects.filter(
            source_system=source,
        ).order_by("-valid_from").first()
        return {
            "in_force": False,
            "reference": held.reference if held else "",
            "expired": bool(held),
        }
    return {
        "in_force": True,
        "reference": row.reference,
        "approved_by": row.approved_by,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "purpose": row.purpose,
    }


def _runs_for(source: SourceSystem, limit: int = 5) -> list[dict]:
    return [
        {
            "id": run.id, "status": run.status, "run_type": run.run_type,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "received": run.records_received,
            "promoted": run.records_promoted,
            "quarantined": run.records_quarantined,
            "rejected": run.records_rejected,
            "note": run.note,
        }
        for run in ConnectorRun.objects
        .filter(connector__source_system=source)
        .order_by("-started_at")[:limit]
    ]


def describe(source: SourceSystem) -> Integration:
    """Everything known about one integration."""
    connector = Connector.objects.filter(
        source_system=source, is_active=True,
    ).first()
    agreement = _agreement_for(source)

    view = Integration(
        code=source.code,
        name=source.name,
        kind=source.kind,
        kind_label=source.get_kind_display(),
        description=source.description,
        is_active=source.is_active,
        connector=connector.name if connector else "",
        agreement=agreement,
        runs=_runs_for(source),
    )

    view.checks.append(Check(
        ok=bool(connector),
        label="Connector registered",
        detail=connector.name if connector else (
            "No connector, so nothing can be pulled for this source. "
            "Records may still arrive by another route."
        ),
    ))
    # The agreement gate is `start_connector_run`'s, and that needs a
    # connector. A source nothing is pulled from — the console
    # channel, a walk-in desk — receives nothing to be authorised, so
    # demanding paperwork for it would be a permanent false alarm and
    # would teach an operator to ignore the list.
    needs_agreement = bool(connector)
    if needs_agreement:
        view.checks.append(Check(
        ok=bool(agreement.get("in_force")),
        label="Data-provision agreement in force",
        detail=(
                f"{agreement['reference']} · approved by "
                f"{agreement.get('approved_by') or '—'}"
                if agreement.get("in_force")
                else (
                    f"{agreement['reference']} has lapsed."
                    if agreement.get("expired")
                    else "None recorded. A connector run is refused "
                         "without one."
                )
            ),
        ))
        if not agreement.get("in_force"):
            view.blockers.append(
                f"No data-provision agreement in force for {source.code}. "
                "AC-DIH-DPA-REQUIRED refuses a run without one.",
            )

    adapter = _ADAPTERS.get(source.kind)
    if adapter is not None:
        adapter(source, view)
    else:
        view.credential = {
            "configured": None,
            "summary": (
                "This kind has no console configuration yet. Nothing is "
                "wrong — it is registered and not wired."
            ),
        }
    return view


def describe_all(*, include_inactive: bool = True) -> list[Integration]:
    """Every registered source, wired or not.

    Ordered so the ones an operator can act on come first: an
    integration with actions, then one with a connector, then the
    rest alphabetically. A screen that led with four unwired channels
    would bury the two that matter.
    """
    sources = SourceSystem.objects.all()
    if not include_inactive:
        sources = sources.filter(is_active=True)
    out = [describe(s) for s in sources.order_by("code")]
    return sorted(
        out,
        key=lambda i: (not i.actions, not i.connector, i.name.lower()),
    )


@register_adapter(SourceSystemKind.KOBO)
def _describe_kobo(source: SourceSystem, view: Integration) -> None:
    """Kobo: a Knox token, a form, and a pull that already dry-runs.

    The dry run is `trigger_connector_pull(dry_run=True)`, which has
    existed since ADR-0007 and opens the run as `run_type=TEST` so it
    stays out of the latency dashboards. Nothing new is built here —
    the screen just stops being the only place that could not reach
    it.
    """
    from .models import KoboCredential

    credential = KoboCredential.objects.filter(source_system=source).first()
    view.direction = "inbound"
    view.credential = {
        "configured": bool(credential and credential.token_encrypted),
        "summary": (
            f"{credential.server_url}"
            + (
                f" · acquired by {credential.acquired_by_username}"
                if credential and credential.acquired_by_username else ""
            )
            if credential else
            "No credential. Added through the source's Django admin page."
        ),
        "last_test_ok": credential.last_test_ok if credential else None,
        "last_test_at": credential.last_test_at if credential else None,
    }
    view.checks.append(Check(
        ok=bool(credential and credential.token_encrypted),
        label="Credential stored",
        detail=view.credential["summary"],
    ))
    if not (credential and credential.token_encrypted):
        view.blockers.append(
            "No Kobo credential. Add one on the source's admin page; "
            "a username and password are exchanged once for a token.",
        )

    view.credential["fields"] = [
        {"name": "server_url", "label": "Server URL", "type": "url",
         "value": credential.server_url if credential else "",
         "required": True,
         "help": "Which Kobo instance this source pulls from."},
        {"name": "username", "label": "Username", "type": "text",
         "value": "", "required": False,
         "help": "With a password, exchanged once for a token. The "
                 "password is never stored."},
        {"name": "password", "label": "Password", "type": "password",
         "value": "", "required": False},
        {"name": "api_token", "label": "API token", "type": "password",
         "value": "", "required": False,
         "help": "Instead of a username and password. The only path "
                 "that works for an account with MFA."},
    ]
    view.credential["save"] = {
        "url": f"/api/v1/dih/source-systems/{source.id}/credential/",
    }
    view.credential["summary"] = (
        view.credential["summary"]
        if credential else
        "Not configured. Add a server and a token to pull from Kobo."
    )

    trigger = f"/api/v1/dih/source-systems/{source.id}/trigger-run/"
    view.actions = {
        # One endpoint, two meanings — `dry_run` is a field on it, not
        # a second route, which is why both point at the same place.
        "dry_run": {"url": trigger, "body": {"dry_run": True}},
        "pull": {"url": trigger, "body": {"dry_run": False}},
    }
    view.extra.append({
        "label": "Watermark",
        "value": str(
            (Connector.objects.filter(source_system=source).first()
             or Connector()).config.get("last_pulled_submission_time", "")
            or "none — the next pull reads everything",
        ),
    })
