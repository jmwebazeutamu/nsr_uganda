"""Django system check — fail startup if DATA_UPLOAD_MAX_MEMORY_SIZE is too
small for the evidence caps this app advertises.

UPD evidence is posted as base64 inside the JSON body, so Django bounds it
with DATA_UPLOAD_MAX_MEMORY_SIZE and rejects oversized requests in
``HttpRequest.body`` — before DRF parses, and therefore before
``_BundleRequest.validate_documents`` can run. If the Django ceiling drops
below what evidence_storage permits, the app's own "max per file" / "max
total" errors become unreachable: a legitimate upload fails with a generic
RequestDataTooBig instead of the specific 400 the API documents.

That is exactly the state the codebase shipped in until 2026-08-08 — the
2.5 MB default is under the ~6.7 MB wire size of one permitted 5 MiB
document — and it was invisible because the endpoint's own limits looked
correct in isolation. This check ties the two numbers together so they
cannot drift apart again silently.
"""

from __future__ import annotations

import math
from typing import Any

from django.conf import settings
from django.core.checks import Error, register

# base64 encodes 3 bytes as 4 characters.
_BASE64_RATIO = 4 / 3

# Headroom for the rest of the JSON envelope: rows, note, entity ids,
# filenames, content types, quoting and padding.
_ENVELOPE_SLACK = 1024 * 1024


@register("update_workflow")
def evidence_upload_ceiling_check(app_configs: Any, **kwargs: Any) -> list[Error]:
    """DATA_UPLOAD_MAX_MEMORY_SIZE must admit the largest VALID bundle, so
    that oversized ones are rejected by our validators rather than by
    Django's transport-level guard."""
    from apps.update_workflow.evidence_storage import (
        MAX_FILE_BYTES,
        MAX_TOTAL_BYTES,
    )

    ceiling = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", None)
    # None means "no limit" — unusual, but not a misconfiguration to block on.
    if ceiling is None:
        return []

    required = math.ceil(MAX_TOTAL_BYTES * _BASE64_RATIO) + _ENVELOPE_SLACK
    if ceiling >= required:
        return []

    mib = 1024 * 1024
    return [Error(
        (
            f"DATA_UPLOAD_MAX_MEMORY_SIZE is {ceiling} bytes "
            f"({ceiling / mib:.1f} MiB) but UPD evidence uploads need at "
            f"least {required} ({required / mib:.1f} MiB): "
            f"MAX_TOTAL_BYTES is {MAX_TOTAL_BYTES / mib:.0f} MiB decoded, "
            f"which is ~{MAX_TOTAL_BYTES * _BASE64_RATIO / mib:.1f} MiB once "
            f"base64-encoded into the JSON body, plus envelope. A single "
            f"{MAX_FILE_BYTES / mib:.0f} MiB document alone is "
            f"~{MAX_FILE_BYTES * _BASE64_RATIO / mib:.1f} MiB on the wire."
        ),
        hint=(
            "Raise DATA_UPLOAD_MAX_MEMORY_SIZE in nsr_mis/settings.py (or the "
            "env var of the same name), or lower MAX_TOTAL_BYTES/"
            "MAX_FILE_BYTES in apps/update_workflow/evidence_storage.py. "
            "Leaving them mismatched makes the endpoint's own size errors "
            "unreachable — clients get a generic RequestDataTooBig instead."
        ),
        id="update_workflow.E001",
    )]
