"""IDV NIRA client — provider seam.

SAD §4.5 / §6.1: registry-side modules (UPD, DIH staging, walk-in
intake) call a single NiraClient interface to verify a NIN. Two
implementations sit behind a settings flag (NIRA_PROVIDER):

    NIRA_PROVIDER=mock  -> MockNiraClient   (default, in-process)
    NIRA_PROVIDER=live  -> LiveNiraClient   (placeholder; raises
                                            NotImplementedError until
                                            the NIRA sandbox creds land
                                            per open item NIRA-O-01)

Callers never import the mock module directly — they go through
get_nira_client() so the swap is a one-line config change at deploy
time and the call sites have no conditional code.
"""

from __future__ import annotations

from typing import Any, Protocol

from django.conf import settings


class NiraClient(Protocol):
    """Verb-shaped contract every NIRA client implementation honours."""

    def verify_nin(self, nin: str) -> dict[str, Any]:
        """Return a dict shaped per apps.identity_verification.mock.

        Keys: status ('match' | 'no_match' | 'mismatch' | 'bad_format'),
        and 'demographics' when status='match'. Implementations may
        raise NiraError to signal an upstream outage that callers must
        queue and retry.
        """


class MockNiraClient:
    """In-process implementation that delegates to apps.identity_
    verification.mock.verify_nin. Used in dev, CI, and any environment
    where NIRA_PROVIDER=mock (the default)."""

    def verify_nin(self, nin: str) -> dict[str, Any]:
        from .mock import verify_nin
        return verify_nin(nin)


class LiveNiraClient:
    """Placeholder for the production NIRA HTTP client.

    Wiring is intentionally absent — sandbox base URL, client cert,
    rate-limit config, and the mTLS chain all depend on NIRA-O-01
    (open item: NIRA sandbox creds + integration MOU). The seam exists
    so call sites never see a conditional 'if mock else live' branch;
    when the credentials land, this class gains an `httpx.Client`
    instance and the body of verify_nin, and every caller picks it up
    by flipping NIRA_PROVIDER=live in the environment.
    """

    def verify_nin(self, nin: str) -> dict[str, Any]:
        raise NotImplementedError(
            "LiveNiraClient is not wired yet — NIRA sandbox creds are "
            "pending (NIRA-O-01). Run with NIRA_PROVIDER=mock until the "
            "integration lands.",
        )


def get_nira_client() -> NiraClient:
    """Factory honouring settings.NIRA_PROVIDER. The choice is read at
    each call so test code can override settings on a per-test basis."""
    provider = (getattr(settings, "NIRA_PROVIDER", "mock") or "").lower()
    if provider == "live":
        return LiveNiraClient()
    if provider == "mock":
        return MockNiraClient()
    raise ValueError(
        f"NIRA_PROVIDER={provider!r} unknown; expected 'mock' or 'live'",
    )
