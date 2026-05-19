"""Code-to-label resolver service backed by ChoiceList / ChoiceOption.

Per ADR-0010: codes are persisted on Household, Member, and inside
source_payload JSON; labels are computed on read against the active
ChoiceList version for the record's intake date.

Cache strategy: two layers of `lru_cache` keyed by (list_name,
as_of_date) and (list_id, language). Both are flushed on
ChoiceList.save() and ChoiceOption.save() via the signal in
apps/reference_data/signals.py. The cache survives across requests
within a single worker process; cross-process invalidation rides on
the dual-approval workflow already in place — an approved revision
flips the ETag on the bundle endpoint, and the next request in each
worker re-warms from the DB.
"""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache

from django.db.models import Q
from django.utils import timezone

from .models import ChoiceList, ChoiceListStatus, ChoiceOption

log = logging.getLogger(__name__)


def _today() -> date:
    """Today in the project timezone (EAT). Wrapped so tests can patch."""
    return timezone.localdate()


@lru_cache(maxsize=512)
def _active_list_id(list_name: str, as_of: date) -> str | None:
    """Resolve the ChoiceList row active at `as_of` for `list_name`.

    Selection rule (ADR-0010 §3): status=ACTIVE, effective_from is
    null or <= as_of, effective_to is null or > as_of. When multiple
    rows match (overlapping windows — open item OI-S22-2), pick the
    highest version.
    """
    qs = (
        ChoiceList.objects
        .filter(list_name=list_name, status=ChoiceListStatus.ACTIVE)
        .filter(Q(effective_from__isnull=True) | Q(effective_from__lte=as_of))
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
        .order_by("-version")
    )
    cl = qs.first()
    return cl.id if cl else None


@lru_cache(maxsize=512)
def _options_map(list_id: str, language: str) -> dict[str, str]:
    """code -> label for the given ChoiceList version and language.

    Returns the union of English rows (always loaded as a fallback)
    and `language` rows (which override English when both exist).
    Only status=ACTIVE options are included — deprecated options are
    not returned, which matches the intake-time selectability rule
    in ChoiceOption.status's docstring.
    """
    rows = (
        ChoiceOption.objects
        .filter(
            choice_list_id=list_id,
            status=ChoiceOption.Status.ACTIVE,
        )
        .values("code", "label", "language")
    )
    by_lang: dict[str, dict[str, str]] = {}
    for r in rows:
        by_lang.setdefault(r["language"], {})[r["code"]] = r["label"]
    primary = by_lang.get(language, {})
    fallback = by_lang.get("en", {})
    # Primary overrides fallback for any code present in both.
    return {**fallback, **primary}


def clear_resolver_cache() -> None:
    """Invalidate every cached lookup. Called by the post_save /
    post_delete signal on ChoiceList and ChoiceOption."""
    _active_list_id.cache_clear()
    _options_map.cache_clear()


def resolve_label(
    list_name: str,
    code: str | int | None,
    language: str = "en",
    as_of: date | None = None,
    *,
    context: dict | None = None,
) -> str:
    """Resolve `code` to its label on `list_name` as of `as_of`.

    Returns the raw code (as a string) and emits a structured
    `ref_data.unmapped_code` warning when the code does not map.
    Returns an empty string for null/empty input — the caller can
    treat that as "field not answered".
    """
    if code is None or code == "":
        return ""
    code_str = str(code)
    as_of = as_of or _today()
    list_id = _active_list_id(list_name, as_of)
    if list_id is None:
        log.warning(
            "ref_data.unmapped_list",
            extra={
                "list_name": list_name,
                "as_of": str(as_of),
                **(context or {}),
            },
        )
        return code_str
    options = _options_map(list_id, language)
    label = options.get(code_str)
    if label is None:
        log.warning(
            "ref_data.unmapped_code",
            extra={
                "list_name": list_name,
                "code": code_str,
                "as_of": str(as_of),
                **(context or {}),
            },
        )
        return code_str
    return label


def resolve_labels(
    list_name: str,
    codes,
    language: str = "en",
    as_of: date | None = None,
    *,
    context: dict | None = None,
) -> list[str]:
    """Multi-select counterpart to resolve_label. Accepts a list, a
    whitespace-separated string (as XLSForm select-multiple stores
    them), or None."""
    if not codes:
        return []
    if isinstance(codes, str):
        codes = codes.split()
    return [resolve_label(list_name, c, language, as_of, context=context) for c in codes]


def resolve_options(
    list_name: str,
    language: str = "en",
    as_of: date | None = None,
) -> list[dict]:
    """Return the active option set for `list_name` at `as_of` as
    a list of `{"code", "label"}` dicts ordered by ChoiceOption
    sort_order then code. Used by the bundle endpoint and by tests."""
    as_of = as_of or _today()
    list_id = _active_list_id(list_name, as_of)
    if list_id is None:
        return []
    # We re-query here (rather than reusing _options_map) so the
    # order matches the source-of-truth ordering in the admin.
    rows = (
        ChoiceOption.objects
        .filter(
            choice_list_id=list_id,
            status=ChoiceOption.Status.ACTIVE,
        )
        .order_by("sort_order", "code")
        .values("code", "label", "language")
    )
    by_code_lang: dict[tuple[str, str], str] = {
        (r["code"], r["language"]): r["label"] for r in rows
    }
    seen_codes: list[str] = []
    for r in rows:
        if r["code"] not in seen_codes:
            seen_codes.append(r["code"])
    out: list[dict] = []
    for code in seen_codes:
        label = (
            by_code_lang.get((code, language))
            or by_code_lang.get((code, "en"))
            or code
        )
        out.append({"code": code, "label": label})
    return out
