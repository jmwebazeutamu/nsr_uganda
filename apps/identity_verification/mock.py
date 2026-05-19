"""NIRA sandbox mock — Sprint 0 item 9.

A deterministic stand-in for the NIRA NIN service per SAD §6.1, so the
DIH and UPD pipelines can be exercised before the live integration is
available. Production swaps the base URL; the contract stays.

Outcome is chosen by the NIN suffix so tests can ask for a specific
behaviour without setting up fixtures:

    suffix "NM"  -> {"status": "no_match"}
    suffix "SU"  -> 503 service_unavailable (caller queues + retries)
    suffix "MM"  -> {"status": "mismatch"}  (NIN known but biographic mismatch)
    everything else (incl. "AB") -> {"status": "match", "demographics": {...}}

Demographics are derived from the NIN itself so the response is stable
across calls. No data leaves the host.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

NIN_REGEX = re.compile(r"^(CM|CF)[A-Z0-9]{12}$")


class NiraError(Exception):
    """Raised when the mock decides to simulate a NIRA outage."""


def _demographics(nin: str) -> dict[str, Any]:
    """Deterministic stub keyed off the NIN."""
    # ChoiceOption codes on the seeded sex list: 1=Male, 2=Female (ADR-0010).
    sex = "2" if nin.startswith("CF") else "1"
    # Treat last 4 chars as a year-of-birth seed. Maps into [1940, 2010].
    seed = sum(ord(c) for c in nin[-4:])
    yob = 1940 + (seed % 71)
    return {
        "nin": nin,
        "sex": sex,
        "date_of_birth": date(yob, 1, 1).isoformat(),
        "surname": f"DemoSurname-{nin[-4:]}",
        "first_name": f"DemoFirst-{nin[-4:]}",
        "issued_at": "2020-01-01",
        "card_status": "active",
    }


def verify_nin(nin: str) -> dict[str, Any]:
    """Mock NIRA /v1/nin/verify. Returns a dict shaped like the real API.

    Raises NiraError for the 'service_unavailable' suffix so the caller
    exercises the queue-and-retry path.
    """
    if not NIN_REGEX.fullmatch(nin):
        return {"status": "bad_format", "detail": "NIN does not match NIRA regex"}

    suffix = nin[-2:]
    if suffix == "SU":
        raise NiraError("NIRA mock simulating service_unavailable")
    if suffix == "NM":
        return {"status": "no_match"}
    if suffix == "MM":
        return {"status": "mismatch", "detail": "NIN found, biographic mismatch"}

    return {"status": "match", "demographics": _demographics(nin)}
