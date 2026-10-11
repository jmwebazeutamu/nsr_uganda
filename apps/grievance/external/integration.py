"""How the STAAC exchange describes itself to the console.

Registered against the `partner_mis` kind so the integrations screen
can show it without DIH knowing what a partner bearer token is. The
generic half — source registered, connector, agreement in force,
recent runs — is `ingestion_hub.integrations`; this adds the three
things only GRM knows: the credential, what is held and waiting, and
that the category bindings decide whether a case files at all.
"""

from __future__ import annotations

from apps.ingestion_hub.integrations import Check, Integration, register_adapter
from apps.ingestion_hub.models import SourceSystemKind

from . import SOURCE_CODE


@register_adapter(SourceSystemKind.PARTNER_MIS)
def describe_staac(source, view: Integration) -> None:
    if source.code != SOURCE_CODE:
        # Another partner MIS may be registered under the same kind
        # one day. It is not this one, and guessing that it works the
        # same way is how a screen starts lying.
        view.credential = {
            "configured": None,
            "summary": "No console configuration for this partner yet.",
        }
        return

    from apps.reference_data.models import ChoiceOption

    from ..intake import STAAC_CATEGORY_LIST
    from ..models import HandoverOutcome, StaacCredential, StaacHandover

    view.direction = "inbound"
    view.registered_by = "migration grievance.0017"

    credential = StaacCredential.objects.filter(is_active=True).first()
    view.credential = {
        "configured": bool(credential and credential.token_encrypted),
        "environment": credential.environment if credential else "",
        "base_url": credential.base_url if credential else "",
        "resuming": bool(credential and credential.cursor),
        "last_pulled_at": credential.last_pulled_at if credential else None,
        "summary": (
            f"{credential.environment} · {credential.base_url}"
            if credential else
            "No credential. The IG issues one through STAAC's "
            "partner-access workspace."
        ),
    }
    view.checks.append(Check(
        ok=bool(credential and credential.token_encrypted),
        label="Credential stored",
        detail=view.credential["summary"],
    ))

    base = "/api/v1/grm/partner-api/staac/"
    view.credential["fields"] = [
        {"name": "environment", "label": "Environment", "type": "text",
         "value": credential.environment if credential else "sandbox",
         "required": True,
         "help": "sandbox or production. Each has its own credential, "
                 "and saving one as live stands the other down."},
        {"name": "base_url", "label": "Base URL", "type": "url",
         "value": credential.base_url if credential else "",
         "required": True,
         "help": "The partner's origin, no path."},
        {"name": "token", "label": "Bearer token", "type": "password",
         "value": "", "required": False,
         "help": "Shown once by STAAC. Blank keeps the stored one; a "
                 "new one clears the resume cursor."},
        {"name": "is_active", "label": "Use this one", "type": "checkbox",
         "value": True, "required": False,
         "help": "Which environment the pull talks to."},
    ]
    view.credential["save"] = {"url": base}
    # Every environment on file, so switching to production is
    # choosing a row rather than editing one in place and losing the
    # URL you were pointing at.
    view.credential["rows"] = [
        {
            "environment": c.environment, "base_url": c.base_url,
            "is_active": c.is_active, "resuming": bool(c.cursor),
            "last_pulled_at": c.last_pulled_at,
        }
        for c in StaacCredential.objects.order_by("environment")
    ]

    options = ChoiceOption.objects.filter(
        choice_list__list_name=STAAC_CATEGORY_LIST,
    )
    total = options.count()
    bound = options.exclude(canonical_code__isnull=True).count()
    view.checks.append(Check(
        ok=total > 0 and bound == total,
        label=f"Category bindings approved — {bound} of {total}",
        detail=(
            "Every STAAC category maps to an NSR one."
            if total and bound == total else
            "Cases carrying an unbound category are held, not lost, and "
            "file once the binding is approved."
        ),
    ))
    if bound < total:
        view.blockers.append(
            f"{total - bound} STAAC category/categories have no approved "
            "binding.",
        )

    held = StaacHandover.objects.filter(outcome=HandoverOutcome.HELD).count()
    if held:
        view.extra.append({
            "label": "Held, awaiting configuration",
            "value": (
                f"{held} snapshot(s) stored and not filed. Nothing is "
                "lost; each files once what it waits for is in place."
            ),
        })

    view.actions = {
        "test": {"url": f"{base}test-connection/", "body": {}},
        "dry_run": {"url": f"{base}dry-run/", "body": {}},
        "pull": {"url": f"{base}run/", "body": {}},
        "configure": {"url": base},
    }
    if held:
        view.actions["file_held"] = {"url": f"{base}run/",
                                     "body": {"file_held": True}}
