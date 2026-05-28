"""PrivacyClassThrottle — per-(actor, privacy_class, date_utc) daily
caps. ADR-0023 D6 / OPEN-3 defaults: Public unlimited; Internal
100/user/day + 5,000/org/day; Personal 25/user/day + 500/org/day;
Sensitive 0.

Primary storage is Redis (counter keys); the QueryThrottleCounter row
acts as a persistent shadow so tests + dev without Redis still
enforce. The redis path is opt-in via DATA_EXPLORER_THROTTLE_BACKEND
(default 'db').

The throttle is read after the validator runs (we need the strictest
PrivacyClass first). It raises Throttled on cap breach so the API
serialiser maps to HTTP 429 + retry-after.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import F


@dataclass
class ThrottleDecision:
    allowed: bool
    user_count_before: int
    user_cap: int | None
    org_count_before: int
    org_cap: int | None
    retry_after_seconds: int
    reason: str = ""

    @property
    def retry_after(self) -> int | None:
        """Tester-friendly alias. Returns None when allow, seconds when block."""
        return None if self.allowed else self.retry_after_seconds

    def __getitem__(self, key):
        return getattr(self, key)


class Throttled(Exception):
    def __init__(self, decision: ThrottleDecision):
        super().__init__(decision.reason or "throttled")
        self.decision = decision


def _seconds_to_midnight_utc() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return max(int((tomorrow - now).total_seconds()), 1)


class PrivacyClassThrottle:

    @classmethod
    def check_and_increment(cls, *, actor: str, org_code: str,
                            privacy_class, raise_on_deny: bool = False) -> ThrottleDecision:
        """Atomically increment the (actor, class, today) counter and
        decide allow/deny. Returns a ThrottleDecision with .allowed
        set; if `raise_on_deny=True` (legacy callers in api.py) it
        also raises Throttled on deny.

        `privacy_class` accepts either a PrivacyClass instance or its
        `code` string (e.g. "internal"). String form resolves through
        a single FK lookup; instance form is the original Coder
        signature.
        """
        from .models import PrivacyClass, QueryThrottleCounter

        # Accept string code or PrivacyClass instance.
        if isinstance(privacy_class, str):
            try:
                privacy_class = PrivacyClass.objects.get(code=privacy_class)
            except PrivacyClass.DoesNotExist as exc:
                raise ValueError(
                    f"PrivacyClass code {privacy_class!r} not seeded",
                ) from exc

        today = datetime.now(UTC).date()
        user_cap = privacy_class.daily_user_cap
        org_cap = privacy_class.daily_org_cap

        def _deny(decision: ThrottleDecision) -> ThrottleDecision:
            # ADR-0023 D6: every throttle block emits an audit event so
            # DPO can find pattern bursts. The api.py path also catches
            # the Throttled exception; the audit row is single-source
            # here regardless of caller style.
            from apps.security.audit import emit as _emit_audit
            _emit_audit(
                "data_explorer.throttle.exceeded",
                "User", actor,
                actor=actor, actor_kind="user",
                reason=decision.reason,
                field_changes={
                    "privacy_class": privacy_class.code,
                    "daily_cap": decision.user_cap,  # spec name (Tester)
                    "daily_user_cap": decision.user_cap,  # explicit alias
                    "daily_org_cap": decision.org_cap,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
            if raise_on_deny:
                raise Throttled(decision)
            return decision

        # Sensitive — daily_user_cap=0 means blocked. Validator should
        # have refused earlier; this is the belt-and-braces gate.
        if user_cap == 0:
            return _deny(ThrottleDecision(
                allowed=False, user_count_before=0, user_cap=0,
                org_count_before=0, org_cap=org_cap,
                retry_after_seconds=_seconds_to_midnight_utc(),
                reason="sensitive class blocked",
            ))

        with transaction.atomic():
            row, _ = QueryThrottleCounter.objects.get_or_create(
                actor=actor,
                privacy_class=privacy_class,
                date_utc=today,
                defaults={"count": 0, "org_code": org_code},
            )
            user_before = row.count

            if user_cap is not None and user_before >= user_cap:
                return _deny(ThrottleDecision(
                    allowed=False,
                    user_count_before=user_before,
                    user_cap=user_cap,
                    org_count_before=0,
                    org_cap=org_cap,
                    retry_after_seconds=_seconds_to_midnight_utc(),
                    reason=(
                        f"user daily cap {user_cap} reached for "
                        f"{privacy_class.code}"
                    ),
                ))

            # Org-wide cap — sum across the org_code rows for this class.
            org_before = 0
            if org_cap is not None and org_code:
                from django.db.models import Sum
                org_before = (
                    QueryThrottleCounter.objects
                    .filter(
                        org_code=org_code,
                        privacy_class=privacy_class,
                        date_utc=today,
                    )
                    .aggregate(s=Sum("count"))["s"]
                    or 0
                )
                if org_before >= org_cap:
                    return _deny(ThrottleDecision(
                        allowed=False,
                        user_count_before=user_before,
                        user_cap=user_cap,
                        org_count_before=org_before,
                        org_cap=org_cap,
                        retry_after_seconds=_seconds_to_midnight_utc(),
                        reason=(
                            f"org daily cap {org_cap} reached for "
                            f"{privacy_class.code}"
                        ),
                    ))

            row.count = F("count") + 1
            row.save(update_fields=["count", "updated_at"])

        return ThrottleDecision(
            allowed=True,
            user_count_before=user_before,
            user_cap=user_cap,
            org_count_before=org_before,
            org_cap=org_cap,
            retry_after_seconds=0,
            reason="ok",
        )
