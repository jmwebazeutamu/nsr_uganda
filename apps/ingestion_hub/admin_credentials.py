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
from django.utils.html import format_html
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
        actions = (test_connection_action,)

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
