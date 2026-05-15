"""Django admin for DIH source-system credentials (US-S11-003b).

The "Source system" admin gains:

1. A kind dropdown that disables NIRA + UBOS with a "(coming soon)"
   suffix until their credential models land — keeps the UI honest
   about what an operator can actually wire today.
2. Per-kind credential editors. Kobo gets a KoboCredentialInline
   that captures `server_url` + `username` + `password`; on save the
   admin form exchanges the username+password for a Knox token via
   `acquire_token()` and writes the token (encrypted) to
   KoboCredential. The plaintext password is held only in the
   request's stack frame.
3. A "Test connection" admin action that calls
   `connection_test.run_test_connection(source_system, ...)` and
   surfaces the result through `messages`.

The plug-in pattern documented in ADR-0007: each new connector that
needs runtime credentials drops in (a) a *Credential model, (b) a
ModelForm with the password-grab fields, and (c) extends
`_CREDENTIAL_REGISTRY` below. The SourceSystemAdmin then
auto-discovers the appropriate form.
"""

from __future__ import annotations

import logging

from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from requests.exceptions import RequestException

from .connection_test import (
    CredentialMissingError,
    UnsupportedConnectorError,
    run_test_connection,
)
from .connectors.kobo import acquire_token
from .models import KoboCredential, SourceSystem, SourceSystemKind

logger = logging.getLogger(__name__)


# Source kinds that have a live connector + credential form. Every
# OTHER kind appears in the dropdown but disabled (see __init__).
SUPPORTED_KINDS = {SourceSystemKind.KOBO}


# --------------------------------------------------------------------
# Kobo credential form — captures username+password (transient) and
# stores only the encrypted token.
# --------------------------------------------------------------------

class KoboCredentialForm(forms.ModelForm):
    """The admin presents this whenever a KOBO SourceSystem is being
    saved. Two authentication paths:

    1. **Username + password** — the form exchanges them for a Knox
       token at save-time via `acquire_token()`. Password lives only
       in the request handler's stack frame and is discarded after.
    2. **Pre-minted API token** — operator pastes a token they
       generated from the Kobo web UI's "Account Settings → Security
       → API token" page. This is the only path that works for
       accounts with MFA enabled (Kobo's `/token/` password exchange
       returns 401 for MFA accounts).

    First-save validation requires EITHER path. Edit allows leaving
    all three blank to keep the existing token, OR providing fresh
    credentials/token to replace it.
    """

    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
        help_text="Kobo username. Required on first save (with password) "
                  "UNLESS providing a pre-minted token below.",
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False, attrs={"autocomplete": "new-password"},
        ),
        help_text="Kobo password. Used ONCE to mint a token; never stored. "
                  "Leave blank if using a pre-minted token.",
    )
    api_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False, attrs={"autocomplete": "off"},
        ),
        help_text="Pre-minted API token from Kobo Account Settings → "
                  "Security. Use this path when the account has MFA "
                  "enabled (the password exchange doesn't support MFA).",
    )

    class Meta:
        model = KoboCredential
        fields = ("server_url",)

    def clean(self):
        """First save requires EITHER username+password OR a pre-minted
        api_token. Edits may leave all three blank to keep the existing
        token. Both username+password AND api_token at once is
        contradictory — surface that explicitly rather than picking one
        path silently."""
        cleaned = super().clean()
        is_creating = self.instance._state.adding
        has_user_pw = bool(cleaned.get("username") and cleaned.get("password"))
        has_token = bool(cleaned.get("api_token"))

        if has_user_pw and has_token:
            raise forms.ValidationError(
                "Provide EITHER username+password OR a pre-minted API "
                "token — not both.",
            )
        if is_creating and not (has_user_pw or has_token):
            raise forms.ValidationError(
                "On first save, provide either username + password "
                "(token will be minted) or a pre-minted API token.",
            )
        return cleaned

    def save(self, commit: bool = True):
        instance: KoboCredential = super().save(commit=False)
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        api_token = self.cleaned_data.get("api_token")
        if api_token:
            # Pre-minted path: trust the token verbatim. The "Test
            # connection" action will confirm it works against the
            # upstream before the operator relies on it.
            instance.token_encrypted = api_token.strip()
            # No upstream username to record; mark the lineage so the
            # audit reader knows the credential didn't transit our
            # acquire_token path.
            instance.acquired_by_username = "(pre-minted)"
        elif username and password:
            # Exchange now, before commit, so that a credential failure
            # surfaces as a form error rather than a half-saved row.
            try:
                token = acquire_token(
                    instance.server_url, username, password,
                )
            except RequestException as exc:
                raise forms.ValidationError(
                    f"Kobo refused the credentials: {exc}",
                ) from exc
            instance.token_encrypted = token
            instance.acquired_by_username = username
        if commit:
            instance.save()
        return instance


class KoboCredentialInline(admin.StackedInline):
    """Inline editor mounted on SourceSystemAdmin when kind=kobo."""

    model = KoboCredential
    form = KoboCredentialForm
    extra = 1
    max_num = 1
    can_delete = True
    verbose_name = "Kobo credential"
    verbose_name_plural = "Kobo credential"
    readonly_fields = ("acquired_by_username", "acquired_at",
                       "last_test_at", "last_test_ok")


# --------------------------------------------------------------------
# Credential registry — extension seam for NIRA + UBOS.
# --------------------------------------------------------------------

# Add an entry here when a new credential model + form lands. The
# SourceSystemAdmin reads this dict to decide which inline(s) to mount
# for the current object's kind.
_CREDENTIAL_REGISTRY: dict[str, type[admin.StackedInline]] = {
    SourceSystemKind.KOBO: KoboCredentialInline,
}


# --------------------------------------------------------------------
# SourceSystemAdmin — kind-aware inline + Test connection action.
# --------------------------------------------------------------------

class SourceSystemForm(forms.ModelForm):
    """Disables the kind dropdown choices for connectors that don't
    have a live credential form yet (NIRA + UBOS). Operators see them
    in the list with a '(coming soon)' suffix so they know what's
    being built."""

    class Meta:
        model = SourceSystem
        fields = ("code", "name", "kind", "description", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "kind" not in self.fields:
            return
        kind_field = self.fields["kind"]
        labelled: list[tuple[str, str]] = []
        for value, label in kind_field.choices:
            if value and value not in SUPPORTED_KINDS:
                label = f"{label} (coming soon)"
            labelled.append((value, label))
        kind_field.choices = labelled


# Max submissions to land per "Pull" click — keeps the admin request
# short enough that an operator doesn't stare at a spinner for a Kobo
# form with 50,000 historical responses. Background-scheduled pulls
# (the future Celery beat task) won't apply this cap.
PULL_BATCH_CAP = 50


@admin.action(description="List Kobo forms (read-only)")
def list_kobo_forms_action(modeladmin, request, queryset):
    """Diagnostic: enumerate the assets each selected Kobo SourceSystem
    can see under its stored token. No DB writes other than the
    standard AuditEvent on read."""
    from apps.security.audit import emit as emit_audit

    from .connection_test import credentials_for
    from .connectors.base import get_connector

    for source in queryset:
        if source.kind != SourceSystemKind.KOBO:
            messages.warning(request, f"{source.code}: not a Kobo source — skipped")
            continue
        connector = get_connector(source.code)
        if connector is None or connector.list_forms is None:
            messages.warning(request, f"{source.code}: no live connector registered")
            continue
        try:
            creds = credentials_for(source)
        except CredentialMissingError as exc:
            messages.error(request, f"{source.code}: {exc}")
            continue
        try:
            forms = connector.list_forms(creds)
        except Exception as exc:  # noqa: BLE001 — surface upstream failures
            messages.error(request, f"{source.code}: list_forms failed: {exc}")
            continue
        emit_audit(
            "list_forms", "source_system", source.id,
            actor=request.user.username or "admin", actor_kind="user",
            reason=f"{len(forms)} assets visible",
        )
        if not forms:
            messages.info(request, f"{source.code}: token sees 0 assets")
            continue
        # Compact rendering — operators just need to see "what's there"
        # to pick a form_id for the pull action.
        rendered = format_html_join(
            "<br>", "&middot; <code>{}</code> {} — {} {}",
            (
                (f["uid"], f["name"] or "(no name)", f["asset_type"],
                 "[deployed]" if f["deployed"] else "[draft]")
                for f in forms
            ),
        )
        messages.success(
            request,
            format_html(
                "{}: {} asset(s) visible:<br>{}",
                source.code, len(forms), rendered,
            ),
        )


@admin.action(description=f"Pull Kobo submissions to RawLanding (first deployed form, ≤{PULL_BATCH_CAP})")
def pull_kobo_submissions_action(modeladmin, request, queryset):
    """Opens an IMPORT ConnectorRun, picks the first deployed form for
    each Kobo source, and lands up to PULL_BATCH_CAP submissions as
    RawLanding rows. Canonicalisation + promotion are NOT triggered —
    that requires the Kobo-to-NSR mapper which is a separate ticket.

    Operators eyeball the result in
    /admin/ingestion_hub/rawlanding/?connector_run__connector__source_system__code=KOBO-PILOT
    """
    from django.utils import timezone

    from .connection_test import credentials_for
    from .connectors.base import get_connector
    from .models import Connector as ConnectorModel
    from .models import ConnectorRunStatus
    from .services import DihError, land_payload, start_connector_run

    actor = request.user.username or "admin"
    for source in queryset:
        if source.kind != SourceSystemKind.KOBO:
            messages.warning(request, f"{source.code}: not a Kobo source — skipped")
            continue
        connector_impl = get_connector(source.code)
        if connector_impl is None or connector_impl.pull_submissions is None:
            messages.warning(request, f"{source.code}: no live connector registered")
            continue
        try:
            creds = credentials_for(source)
        except CredentialMissingError as exc:
            messages.error(request, f"{source.code}: {exc}")
            continue

        # Resolve the form to pull: first deployed asset wins.
        try:
            forms = [f for f in connector_impl.list_forms(creds) if f["deployed"]]
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"{source.code}: list_forms failed: {exc}")
            continue
        if not forms:
            messages.warning(
                request, f"{source.code}: no deployed forms — nothing to pull",
            )
            continue
        form = forms[0]

        # Resolve a Connector row to anchor the run. The test_connection
        # action lazily materialised one under name="test-connection" —
        # reuse it if present, else create a sibling. The
        # start_connector_run() service enforces AC-DIH-DPA-REQUIRED.
        connector_row, _ = ConnectorModel.objects.get_or_create(
            source_system=source, name=f"kobo-{form['uid']}",
            defaults={"config": {"kobo_form_uid": form["uid"]}},
        )
        try:
            run = start_connector_run(connector_row, actor=actor)
        except DihError as exc:
            messages.error(request, f"{source.code}: {exc}")
            continue

        landed = 0
        try:
            for raw in connector_impl.pull_submissions(creds, form_id=form["uid"]):
                if landed >= PULL_BATCH_CAP:
                    break
                source_ref = str(raw.get("_id") or raw.get("_uuid") or "")
                land_payload(run, raw, source_reference=source_ref)
                landed += 1
        except Exception as exc:  # noqa: BLE001
            run.status = ConnectorRunStatus.FAILED
            run.finished_at = timezone.now()
            run.note = f"pull failed after {landed} row(s): {exc}"
            run.save(update_fields=("status", "finished_at", "note"))
            messages.error(
                request, f"{source.code}: pull failed after {landed} row(s): {exc}",
            )
            continue

        run.status = ConnectorRunStatus.SUCCEEDED
        run.finished_at = timezone.now()
        run.note = (
            f"pulled {landed} row(s) from form {form['uid']} ({form['name']})"
            + (f"; cap {PULL_BATCH_CAP} hit" if landed >= PULL_BATCH_CAP else "")
        )
        run.save(update_fields=("status", "finished_at", "note"))

        run_url = reverse(
            "admin:ingestion_hub_connectorrun_change", args=[run.id],
        )
        landings_url = (
            "/admin/ingestion_hub/rawlanding/"
            f"?connector_run__id__exact={run.id}"
        )
        messages.success(
            request,
            format_html(
                "{}: landed {} row(s) from <code>{}</code>. "
                "<a href='{}'>view run</a> &middot; "
                "<a href='{}'>view landings</a>",
                source.code, landed, form["uid"], run_url, landings_url,
            ),
        )


@admin.action(description="Test connection (live probe)")
def test_connection_action(modeladmin, request, queryset):
    """Fires `run_test_connection` once per selected SourceSystem.
    Each call writes a ConnectorRun row of type=TEST and an
    AuditEvent regardless of outcome — operations needs both the
    happy and unhappy attempts on record."""
    for source in queryset:
        try:
            run, result = run_test_connection(
                source, actor=request.user.username or "admin",
            )
        except CredentialMissingError as exc:
            messages.error(request, f"{source.code}: {exc}")
            continue
        except UnsupportedConnectorError as exc:
            messages.warning(request, f"{source.code}: {exc}")
            continue

        run_url = reverse(
            "admin:ingestion_hub_connectorrun_change", args=[run.id],
        )
        if result.ok:
            messages.success(
                request,
                format_html(
                    "{}: connection OK ({} ms, version: {}). "
                    "<a href='{}'>view run</a>",
                    source.code, result.latency_ms,
                    result.server_version or "—", run_url,
                ),
            )
        else:
            messages.error(
                request,
                format_html(
                    "{}: connection FAILED — {}. <a href='{}'>view run</a>",
                    source.code, result.error or "unknown error", run_url,
                ),
            )


# Patch the existing SourceSystemAdmin (registered in admin.py) by
# unregistering + re-registering with the new behaviour. Keeps the
# original SourceSystemAdmin definition tidy.
def _install_source_system_admin() -> None:
    try:
        admin.site.unregister(SourceSystem)
    except admin.sites.NotRegistered:
        pass

    @admin.register(SourceSystem)
    class SourceSystemAdmin(admin.ModelAdmin):
        form = SourceSystemForm
        list_display = (
            "code", "name", "kind", "is_active", "last_test_display",
            "updated_at",
        )
        list_filter = ("kind", "is_active")
        search_fields = ("code", "name")
        actions = (
            test_connection_action,
            list_kobo_forms_action,
            pull_kobo_submissions_action,
        )

        def get_inline_instances(self, request, obj=None):
            """Show the credential inline that matches the saved kind.
            When the object is new (obj is None) we can't know which
            inline to mount — operators save the SourceSystem first,
            then come back to fill the credential."""
            instances: list = []
            if obj is None:
                return instances
            inline_cls = _CREDENTIAL_REGISTRY.get(obj.kind)
            if inline_cls is not None:
                instances.append(inline_cls(self.model, self.admin_site))
            return instances

        @admin.display(description="Last test", ordering=None)
        def last_test_display(self, obj: SourceSystem) -> str:
            """Renders the most-recent test outcome from the credential
            row. For un-tested or non-Kobo sources, shows a dash."""
            if obj.kind != SourceSystemKind.KOBO:
                return "—"
            cred = getattr(obj, "kobo_credential", None)
            if cred is None or cred.last_test_at is None:
                return "—"
            tone = "#198754" if cred.last_test_ok else "#b00"
            label = "OK" if cred.last_test_ok else "FAIL"
            return format_html(
                "<span style='color:{}'>{}</span> {:%Y-%m-%d %H:%M}",
                tone, label, cred.last_test_at,
            )


_install_source_system_admin()
