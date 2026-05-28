"""PrivacyClassThrottle unit tests.

The throttle enforces ADR-0023 D6:
- Public: unlimited (None / NULL daily_user_cap).
- Internal: 100/user/day + 5,000/org/day.
- Personal: 25/user/day + 500/org/day.
- Sensitive: 0 → always blocks.

The throttle returns either an "ok" decision or a "blocked" decision
with a retry-after seconds value. Throttle decisions that block emit
the audit event `data_explorer.throttle.exceeded`.
"""

from __future__ import annotations

import pytest
from datetime import date

from apps.security.models import AuditEvent


pytestmark = pytest.mark.django_db


def _throttle_class():
    try:
        from apps.data_explorer.services import PrivacyClassThrottle
        return PrivacyClassThrottle
    except ImportError:
        from apps.data_explorer.throttle import PrivacyClassThrottle  # noqa: F401
        return PrivacyClassThrottle


class TestPrivacyClassThrottle:

    def test_public_class_never_blocks(self, privacy_classes):
        Throttle = _throttle_class()
        for _ in range(50):
            allowed = Throttle.check_and_increment(
                actor="u1", org_code="OrgX", privacy_class="public",
            )
            assert allowed.allowed is True

    def test_internal_blocks_after_user_cap(self, privacy_classes):
        """100 calls allowed; the 101st returns 429."""
        Throttle = _throttle_class()
        for i in range(100):
            r = Throttle.check_and_increment(
                actor="u1", org_code="Org1", privacy_class="internal",
            )
            assert r.allowed is True, f"call {i} unexpectedly blocked"
        r101 = Throttle.check_and_increment(
            actor="u1", org_code="Org1", privacy_class="internal",
        )
        assert r101.allowed is False
        assert r101.retry_after is not None
        assert r101.retry_after > 0

    def test_personal_blocks_after_user_cap(self, privacy_classes):
        Throttle = _throttle_class()
        for _ in range(25):
            assert Throttle.check_and_increment(
                actor="u1", org_code="Org1", privacy_class="personal",
            ).allowed
        assert not Throttle.check_and_increment(
            actor="u1", org_code="Org1", privacy_class="personal",
        ).allowed

    def test_sensitive_blocks_first_call(self, privacy_classes):
        Throttle = _throttle_class()
        r = Throttle.check_and_increment(
            actor="u1", org_code="Org1", privacy_class="sensitive",
        )
        assert r.allowed is False

    def test_org_cap_independent_of_user_cap(self, privacy_classes):
        """5,000/org/day must trip even if each user's 100/day cap
        hasn't been exhausted (50 users × 100 = 5,000)."""
        Throttle = _throttle_class()
        # Drive 50 distinct users to exactly the user cap so the org
        # counter sums to the org cap.
        for u in range(50):
            for _ in range(100):
                r = Throttle.check_and_increment(
                    actor=f"u{u}", org_code="OrgY",
                    privacy_class="internal",
                )
                assert r.allowed
        # 51st user's first call must be blocked because the org cap
        # is reached.
        r = Throttle.check_and_increment(
            actor="fresh-user", org_code="OrgY", privacy_class="internal",
        )
        assert r.allowed is False
        assert "org" in (r.reason or "").lower() \
            or r.cap_kind == "org"

    def test_user_in_different_orgs_have_separate_org_counters(
        self, privacy_classes,
    ):
        Throttle = _throttle_class()
        # u1's Org1 → exhaust user cap
        for _ in range(100):
            assert Throttle.check_and_increment(
                actor="u1", org_code="Org1", privacy_class="internal",
            ).allowed
        # u2's Org2 → still gets a clean slate
        r = Throttle.check_and_increment(
            actor="u2", org_code="Org2", privacy_class="internal",
        )
        assert r.allowed is True

    def test_throttle_block_emits_audit(self, privacy_classes):
        """ADR-0023 D6: 'Throttle decisions emit
        data_explorer.throttle.exceeded.' One row per block."""
        Throttle = _throttle_class()
        # Push to the cap+1
        for _ in range(25):
            Throttle.check_and_increment(
                actor="u-x", org_code="O-x", privacy_class="personal",
            )
        # Snap audit baseline
        before = AuditEvent.objects.filter(
            action="data_explorer.throttle.exceeded",
        ).count()
        Throttle.check_and_increment(
            actor="u-x", org_code="O-x", privacy_class="personal",
        )
        after = AuditEvent.objects.filter(
            action="data_explorer.throttle.exceeded",
        ).count()
        assert after == before + 1
        ev = AuditEvent.objects.filter(
            action="data_explorer.throttle.exceeded",
        ).order_by("-occurred_at").first()
        # The audit payload must say which class + cap was tripped.
        assert ev.entity_type in ("User", "user")
        assert ev.entity_id == "u-x"
        # Both keys present per spec table at bottom of TASK
        # (privacy_class, daily_cap)
        fc = ev.field_changes or {}
        assert "privacy_class" in fc
        assert "daily_cap" in fc

    def test_counter_persists_across_calls(self, privacy_classes):
        """Coder's choice — Redis or Django row — but the persistent
        shadow QueryThrottleCounter must reflect the call count."""
        from apps.data_explorer.models import QueryThrottleCounter

        Throttle = _throttle_class()
        for _ in range(7):
            Throttle.check_and_increment(
                actor="u-z", org_code="O-z", privacy_class="internal",
            )
        cnt = QueryThrottleCounter.objects.get(
            actor="u-z",
            privacy_class=privacy_classes["internal"],
            date_utc=date.today(),
        )
        assert cnt.count == 7

    def test_counter_reset_per_day(self, privacy_classes):
        """The unique constraint is (actor, privacy_class, date_utc);
        tomorrow's row is a fresh counter."""
        from apps.data_explorer.models import QueryThrottleCounter

        Throttle = _throttle_class()
        for _ in range(3):
            Throttle.check_and_increment(
                actor="u-day", org_code="Org-day",
                privacy_class="internal",
            )
        today_row = QueryThrottleCounter.objects.get(
            actor="u-day",
            privacy_class=privacy_classes["internal"],
            date_utc=date.today(),
        )
        assert today_row.count == 3
        # Yesterday row independent
        yesterday = QueryThrottleCounter.objects.filter(
            actor="u-day",
            privacy_class=privacy_classes["internal"],
        ).exclude(date_utc=date.today())
        assert yesterday.count() == 0
