"""DocuSign client behind the PARTNERS_DOCUSIGN_ENABLED feature flag.

This is a shell — the concrete REST/SDK calls land when the
DocuSign account is provisioned (open item NIRA-O-01-equivalent
for partners). For now the class lifts the StubSignatureProvider
contract so wiring it up later is a drop-in.

Per ADR-0012 §"DocuSign integration shape": single shared account,
per-OrganisationType template selected by template_key
(derived from partner.type via apps.partners.services.signature.
_template_key_for).
"""

from __future__ import annotations

from apps.partners.services.signature import (
    EnvelopeResult,
    SignatureProvider,
)


class DocuSignProvider(SignatureProvider):  # pragma: no cover (shell)
    def __init__(self) -> None:
        # TODO(US-S23-XXX, partner-affairs-lead): wire DocuSign SDK
        # credentials from settings.PARTNERS_DOCUSIGN_* and template
        # mapping from ChoiceOption metadata.
        raise NotImplementedError(
            "DocuSign client is not yet provisioned. Set "
            "PARTNERS_DOCUSIGN_ENABLED=False (the default) to use "
            "the StubSignatureProvider."
        )

    def send_envelope(self, signature, template_key: str) -> EnvelopeResult:
        ...

    def cancel_envelope(self, signature) -> None:
        ...
