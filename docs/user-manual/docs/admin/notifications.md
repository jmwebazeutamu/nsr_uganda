# Notifications

!!! info "Status"
    **Built and in use** — SMTP wiring + four workflow surfaces live as of v0.3 (2026-05-27). UPD / GRM / citizen email notifications remain blocked on Keycloak User-table sync.

Transactional email goes out at every lifecycle transition that has a clear external party to notify. The system uses one shared helper (`apps.security.notifications.send_notification`) so audit emission, recipient normalisation, and fail-silently semantics are identical across every consumer.

## Workflow → recipient matrix

| Workflow | Trigger | Recipients | Audit action |
|---|---|---|---|
| **PMT** — submit for sign-off | `submit_for_approval` | MGLSD Steward (step 2) | `pmt.signoff.notified` |
| **PMT** — chain advances | `sign_step` (not last) | Next pending signer (UBOS DG) | `pmt.signoff.notified` |
| **PMT** — model activated | `sign_step` (final) | Author + every prior signer | `pmt.activation.notified` |
| **PMT** — rejected | `reject_step` | Author (verbatim reason) | `pmt.rejection.notified` |
| **DSA** — chain advances | `record_signature` (next is in-console) | Next pending signer | `dsa.signoff.notified` |
| **DSA** — activated | `record_signature` (final) | Every signer + `Partner.primary_email` | `dsa.activation.notified` |
| **DSA** — declined | `decline_signature` | Every signer (signed + pending) + `Partner.primary_email`, verbatim reason | `dsa.decline.notified` |
| **Programme** — submit for sign-off | `submit_for_signoff` | NSR Coordinator (step 1) | `programme.signoff.notified` |
| **Programme** — chain advances | `sign_step` (not last) | Next pending signer | `programme.signoff.notified` |
| **Programme** — activated | `sign_step` (final) | Creator + every signer | `programme.activation.notified` |
| **Programme** — rejected | `reject_step` | Every expected signer + creator, verbatim reason | `programme.rejection.notified` |
| **DRS** — approved | `approve_data_request` | `Partner.primary_email` + `DataRequest.requester` | `data_request.approved.notified` |
| **DRS** — rejected | `reject_data_request` | Both, verbatim reason | `data_request.rejected.notified` |
| **DRS** — delivered | `deliver_data_request` | Both, with **manifest SHA-256** + row count + expiry | `data_request.delivered.notified` |
| **DPO** — audit chain break | `verify_audit_chain_task` | `DPO_EMAIL` (env-gated) + Slack webhook | (existing audit row from the verify task) |

The DocuSign envelope for DSA step 1 is sent by DocuSign itself when `PARTNERS_DOCUSIGN_ENABLED=True`. The NSR MIS notification helper deliberately does NOT duplicate that email — it only emails in-console signers (steps 2 + 3).

## How the helper behaves

`send_notification` wraps `django.core.mail.send_mail` with two cross-cutting concerns:

1. **Audit emission.** Every attempt writes an `AuditEvent` linked to the originating entity (PMT model version, DSA, Programme, DataRequest). Three possible actions:
    - `notification.sent` (or the per-workflow code like `pmt.signoff.notified`) — when SMTP accepted the message.
    - `notification.failed` — exception was raised by `send_mail`. The exception class + message are captured in `reason`; the workflow continues anyway. Use this row to triage SMTP outages.
    - `notification.skipped` — no recipients (e.g. `Partner.primary_email` is empty). The row records the subject + a reason so DPO can find the gap.
2. **Fail-silently.** Every exception path catches and audits. PMT activation, DSA signing, etc. never roll back on email failure — the audit-bearing workflow always completes. Email is best-effort; the audit chain is the durable record.

Recipient handling: lists are deduped, blank/None entries are dropped, whitespace is stripped. Multiple roles that happen to resolve to the same email get one mail.

## Operational gotchas

### Production password rotation

The SMTP password lives in the secrets manager (or local `.env`, gitignored). To rotate:

1. Generate a new password on the `comms.quasar.ug` mailserver for `admin@quasar.ug`.
2. Update the secret in the secrets manager.
3. Restart the web + celery workers (Django reads env at boot).
4. Smoke-test from the Django shell:
   ```python
   from django.core.mail import send_mail
   send_mail("[NSR MIS] rotation smoke test", "body", None, ["you@example.com"], fail_silently=False)
   ```
5. If the test fails, check the `apps.security.notifications` logs and the `notification.failed` audit rows.

### Empty `Partner.primary_email`

The DSA activation and DRS delivery flows email `Partner.primary_email`. When that field is empty the helper writes a `notification.skipped` row (the workflow still completes). To find partners missing the contact field:

```sql
SELECT id, code, name
FROM partners_partner
WHERE primary_email = '' OR primary_email IS NULL
ORDER BY name;
```

Add the email through `apps/partners/admin.py` or `/api/v1/partners/<id>/` PATCH.

### Why some workflows are NOT yet wired

| Workflow | Blocker |
|---|---|
| UPD change-request approve / reject / hold | `ChangeRequest.requester` is a CharField operator-id, not an email. Needs a Keycloak User-table sync (US-S2-002) before we can resolve requester → inbox. |
| GRM escalation / resolution | `Grievance.assigned_to` and citizen reporter are identifiers, no email fields. |
| Citizen receipt at intake | No household contact email captured on the intake form yet. Future citizen portal work. |
| DDUP merge → enrolled programmes | The programme-link join needs to be modelled before we know who to notify. |

### Reconciling failed notifications

Query the audit chain for delivery gaps:

```python
from apps.security.models import AuditEvent

# Every failed attempt in the last 24 hours
failed = AuditEvent.objects.filter(
    action="notification.failed",
    occurred_at__gte=timezone.now() - timedelta(hours=24),
).order_by("occurred_at")

for event in failed:
    print(event.entity_type, event.entity_id, event.reason)
    print("  subject:", (event.field_changes or {}).get("subject"))
    print("  recipients:", (event.field_changes or {}).get("recipients"))
```

The same query with `action="notification.skipped"` surfaces records where we had nothing to send to — useful for finding data-quality gaps in partner contacts.

## Related

- [Environment variables](environment.md) — `EMAIL_*` configuration
- [PMT module](../modules/pmt.md) — sign-off lifecycle + notifications
- [Partners module](../modules/partners.md) — DSA + Programme sign-off chains
- [DRS module](../modules/api-drs.md) — request-lifecycle notifications
- [DPO operations](runbooks.md) — chain-break alert configuration
