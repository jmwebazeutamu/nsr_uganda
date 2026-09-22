"""Duplicate discovery runs, and runs safely.

Nothing called the three discover_* services: not the DIH pipeline, not
Celery beat, not an endpoint, not a command. Tier 2 and tier 3 had
therefore never produced a pair in the registry's lifetime, and the
hourly auto-merge sweep had been a no-op since the day it was scheduled.

The riskiest part of switching discovery on is not the discovery — it is
that auto-merge was waiting for it. On dev, thirteen pairs would have
crossed the 0.95 threshold and been merged unattended within the hour.
"""

from datetime import date

import pytest

from apps.data_management.models import Household, Member
from apps.reference_data.models import GeographicUnit
from apps.ddup.models import (
    DdupDiscoveryRun, DdupModelVersion, DiscoveryRunStatus, MatchPair,
    ModelStatus, PairStatus,
)
from apps.ddup.services import auto_merge_high_confidence_pairs, run_discovery


@pytest.fixture
def household(db):
    """Minimal 7-level ladder for FK satisfaction — same shape as the
    fixture in tests.py."""
    nodes = {}
    for level, key, parent_key in [
        ("region", "r", None), ("sub_region", "sr", "r"), ("district", "d", "sr"),
        ("county", "c", "d"), ("sub_county", "sc", "c"),
        ("parish", "p", "sc"), ("village", "v", "p"),
    ]:
        nodes[key] = GeographicUnit.objects.create(
            level=level, code=f"DS-{key.upper()}", name=key.title(),
            parent=nodes.get(parent_key), effective_from=date(2026, 1, 1),
        )
    return Household.objects.create(
        region=nodes["r"], sub_region=nodes["sr"], district=nodes["d"],
        county=nodes["c"], sub_county=nodes["sc"], parish=nodes["p"],
        village=nodes["v"], urban_rural="2",
    )


@pytest.fixture
def twins(household):
    """Two members of one household sharing a NIN — the tier-1 case."""
    from apps.security.hashing import nin_hash

    shared = nin_hash("CM90000000001X")
    return [
        Member.objects.create(
            household=household, line_number=i, surname="Okello",
            first_name="Robert", sex="1", date_of_birth=date(1990, 5, 1),
            nin_hash=shared,
        )
        for i in (1, 2)
    ]


@pytest.fixture(autouse=True)
def active_model(db):
    """An active DdupModelVersion, which get_active_model_version()
    requires. Seeded by script in the real environments, so the test
    database has none."""
    model, _ = DdupModelVersion.objects.get_or_create(
        version=1,
        defaults={
            "description": "test model",
            "author": "tests",
            "status": ModelStatus.ACTIVE,
            "config": {"tier3": {
                "weights": {
                    "surname": 0.30, "first_name": 0.30,
                    "date_of_birth": 0.15, "sex": 0.10, "village": 0.15,
                },
                "threshold": 0.85,
                "auto_merge_threshold": 0.95,
                # auto_merge_enabled deliberately absent — off by default.
            }},
        },
    )
    if model.status != ModelStatus.ACTIVE:
        model.status = ModelStatus.ACTIVE
        model.save(update_fields=["status"])
    return model


@pytest.mark.django_db
class TestAutoMergeIsOff:
    def test_it_does_nothing_unless_the_model_version_enables_it(self):
        """Auto-merge soft-deletes a Member with nobody in the loop, so
        it is off unless an approved model version says otherwise."""
        result = auto_merge_high_confidence_pairs()
        assert result["merged"] == 0
        assert result.get("disabled") == 1

    def test_the_switch_lives_in_the_approved_model_version(self):
        """Not in settings — enabling it must go through the same dual
        approval as the weights and the threshold."""
        model = DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
        assert model is not None
        cfg = (model.config or {}).get("tier3") or {}
        assert not cfg.get("auto_merge_enabled", False), (
            "auto-merge is enabled on the active model version — that is a "
            "policy decision, and this test is the record that it was made"
        )

    def test_enabling_it_is_a_config_change_not_a_code_change(self):
        model = DdupModelVersion.objects.filter(status=ModelStatus.ACTIVE).first()
        config = dict(model.config or {})
        config["tier3"] = {**(config.get("tier3") or {}), "auto_merge_enabled": True}
        model.config = config
        model.save(update_fields=["config"])

        result = auto_merge_high_confidence_pairs()
        assert "disabled" not in result, (
            "the flag did not take effect — auto-merge cannot be turned on "
            "without a code change"
        )


@pytest.mark.django_db
class TestDiscoveryRuns:
    def test_a_run_is_recorded_with_what_it_did(self):
        run = run_discovery(actor="test")
        assert run.status == DiscoveryRunStatus.SUCCEEDED
        assert run.finished_at is not None
        assert run.members_considered == Member.objects.filter(is_deleted=False).count()
        assert DdupDiscoveryRun.objects.count() == 1

    def test_the_first_run_is_a_full_sweep(self):
        """No previous run means no watermark, so everything is compared
        once."""
        run = run_discovery(actor="test")
        assert run.scanned_from is None

    def test_the_next_run_only_looks_at_what_changed(self):
        first = run_discovery(actor="test")
        second = run_discovery(actor="test")
        assert second.scanned_from == first.started_at, (
            "the second run re-swept everything — at national scale that is "
            "~2x10^10 comparisons a night"
        )

    def test_full_forces_a_sweep_even_with_a_watermark(self):
        run_discovery(actor="test")
        forced = run_discovery(full=True, actor="test")
        assert forced.scanned_from is None

    def test_re_running_creates_no_duplicate_pairs(self):
        run_discovery(actor="test")
        after_first = MatchPair.objects.count()
        run_discovery(full=True, actor="test")
        assert MatchPair.objects.count() == after_first


@pytest.mark.django_db
class TestResolvedPairsStayResolved:
    """The property that makes any cadence safe. If discovery resurrected
    decisions, a nightly job would hand an operator the same rejected
    pair every morning."""

    def test_a_rejected_pair_is_not_re_created_as_pending(self, twins):
        run_discovery(full=True, actor="test")
        pair = MatchPair.objects.first()
        assert pair is not None, "tier 1 found no pair for two members sharing a NIN"
        pair.status = PairStatus.REJECTED
        pair.save(update_fields=["status"])

        run_discovery(full=True, actor="test")
        pair.refresh_from_db()
        assert pair.status == PairStatus.REJECTED
        assert MatchPair.objects.filter(
            record_a_id=pair.record_a_id, record_b_id=pair.record_b_id,
        ).count() == 1


@pytest.mark.django_db
class TestTheDihUsesTheSharedTierOne:
    """CLAUDE.md: one implementation, two callers. The DIH gate used to
    carry its own copy of the tier-1 rule."""

    def test_the_dih_delegates_to_the_ddup_service(self):
        import inspect

        from apps.ingestion_hub import services as dih

        source = inspect.getsource(dih._discover_stage_candidates)
        assert "tier1_candidates_for_nin" in source, (
            "the DIH gate has its own tier-1 implementation again"
        )
        assert "nin_hash=" not in source, (
            "the DIH gate is querying Member.nin_hash directly rather than "
            "going through the shared predicate"
        )

    def test_both_callers_find_the_same_members(self, twins):
        """A payload carrying the twins' NIN must surface exactly the
        members the registry tier would pair."""
        from apps.ddup.services import members_sharing_nin_hash
        from apps.ingestion_hub.services import _discover_stage_candidates

        from_registry = set(members_sharing_nin_hash(twins[0].nin_hash))
        assert from_registry == {twins[0].id, twins[1].id}

        payload = {"members": [{"nin": "CM90000000001X"}]}
        from_dih = {c["member_id"] for c in _discover_stage_candidates(payload)}
        assert from_dih == from_registry, (
            "the DIH gate and the registry disagree about who shares this NIN"
        )


class TestItIsActuallyScheduled:
    """The defect was never in the matching code — it was that nothing
    ever called it. These assert the wiring exists."""

    def test_beat_runs_discovery_nightly(self):
        from nsr_mis.celery import app

        schedule = app.conf.beat_schedule
        entry = schedule.get("ddup-nightly-discovery")
        assert entry is not None, (
            "discovery is not scheduled — the three discover_* services "
            "would go back to never being called"
        )
        assert entry["task"] == "apps.ddup.tasks.discover_pairs_task"
        assert entry["schedule"].hour == {4}
        assert entry["schedule"].minute == {0}

    def test_it_runs_after_the_jobs_that_write_members(self):
        """Discovery reads every live Member, so it goes last in the
        nightly chain rather than alongside the PMT recompute."""
        from nsr_mis.celery import app

        slots = {}
        for name, entry in app.conf.beat_schedule.items():
            sched = entry["schedule"]
            hour, minute = getattr(sched, "hour", set()), getattr(sched, "minute", set())
            if len(hour) == 1 and len(minute) == 1:
                slots[(next(iter(hour)), next(iter(minute)))] = name

        mine = next(h for (h, m), n in slots.items() if n == "ddup-nightly-discovery")
        others = [h for (h, _m), n in slots.items() if n != "ddup-nightly-discovery"]
        assert mine > max(others), (
            f"discovery runs at {mine}:00, not after every other nightly "
            f"job (latest is {max(others)}:00)"
        )
        assert len([n for n in slots.values() if n == "ddup-nightly-discovery"]) == 1

    def test_the_task_defaults_to_incremental(self):
        import inspect

        from apps.ddup.tasks import discover_pairs_task

        signature = inspect.signature(discover_pairs_task)
        assert signature.parameters["full"].default is False, (
            "a nightly full sweep is ~2x10^10 comparisons at national scale"
        )
