"""ADR-0045 — the pipeline that calls the models.

Real ORM households and real Celery wiring, not stand-ins: the earlier suite
proved the scorers on stubs, and a stub passes against fields no model row
carries (see the two-vocabularies note).
"""

from unittest import mock

import pytest
from django.utils import timezone

from apps.ai_services import services as svc
from apps.ai_services import tasks
from apps.ai_services.models import AiRun, AiSuggestion, FeatureCode, FeatureState
from apps.ai_services.tests import active_model, linear, pair, robust
from apps.data_management.models import Household, Member
from apps.ddup.models import DdupModelVersion
from apps.ddup.tests import model_config
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db


def make_household(geo, size, n_members=1):
    h = Household.objects.create(
        region=geo["r"], sub_region=geo["sr"], district=geo["d"], county=geo["c"],
        sub_county=geo["sc"], parish=geo["p"], village=geo["v"], urban_rural="2",
        reported_household_size=size,
    )
    for i in range(n_members):
        Member.objects.create(household=h, line_number=i + 1, surname="S", first_name="F", sex="1")
    return h


@pytest.fixture
def anomaly_shadow(enabled):
    m = active_model(FeatureCode.DQA_ANOMALY, robust())
    svc.attach_model(FeatureCode.DQA_ANOMALY, m, actor="ops")
    svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.SHADOW, actor="ops", reason="measure")


class TestSwitchedOffIsQuiet:
    def test_both_tasks_do_nothing_and_do_not_fail(self, geo):
        make_household(geo, 5)
        assert tasks.rank_pending_pairs_task() == {"status": "off"}
        assert tasks.score_recent_households_task() == {"status": "off"}
        assert not AiRun.objects.exists() and not AuditEvent.objects.filter(action__startswith="ai.").exists()


class TestAnomalyFeed:
    def test_scores_real_orm_households(self, geo, anomaly_shadow):
        make_household(geo, 5)
        outlier = make_household(geo, 40)
        out = tasks.score_recent_households_task()
        assert (out["status"], out["scored"], out["state"]) == ("ok", 2, "shadow")
        flagged = AiSuggestion.objects.get(subject_id=str(outlier.id))
        assert flagged.details["flagged"] is True

    def test_an_idle_hour_writes_nothing(self, geo, anomaly_shadow):
        make_household(geo, 5)
        tasks.score_recent_households_task()
        events = AuditEvent.objects.filter(action="ai.inference.batch").count()
        assert tasks.score_recent_households_task() == {"status": "nothing_new"}
        assert AuditEvent.objects.filter(action="ai.inference.batch").count() == events
        assert AiRun.objects.count() == 1

    def test_only_changed_households_are_rescored(self, geo, anomaly_shadow):
        a, b = make_household(geo, 5), make_household(geo, 6)
        tasks.score_recent_households_task()
        b.reported_household_size = 7
        b.save()
        out = tasks.score_recent_households_task()
        assert out["scored"] == 1
        assert AiRun.objects.order_by("-started_at").first().suggestions.get().subject_id == str(b.id)
        assert str(a.id) not in [s.subject_id for s in AiRun.objects.order_by("-started_at").first().suggestions.all()]

    def test_a_batch_limit_resumes_where_it_stopped(self, geo, anomaly_shadow):
        ids = {str(make_household(geo, 5).id) for _ in range(5)}
        first = tasks.score_recent_households_task(limit=2)
        seen = {s.subject_id for s in AiSuggestion.objects.all()}
        for _ in range(6):
            if tasks.score_recent_households_task(limit=2) == {"status": "nothing_new"}:
                break
        seen = {s.subject_id for s in AiSuggestion.objects.all()}
        assert first["scored"] == 2 and seen == ids

    def test_deleted_households_are_not_scored(self, geo, anomaly_shadow):
        h = make_household(geo, 5)
        Household.objects.filter(pk=h.pk).update(is_deleted=True, updated_at=timezone.now())
        assert tasks.score_recent_households_task() == {"status": "nothing_new"}

    def test_the_kill_switch_stops_the_next_run(self, geo, anomaly_shadow):
        make_household(geo, 5)
        svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.OFF, actor="ops", reason="incident")
        assert tasks.score_recent_households_task() == {"status": "off"}
        assert not AiRun.objects.exists()

    def test_the_member_age_path_scores_nothing_on_real_members(self, geo, enabled):
        """The payload producer reads `age`; Member stores `age_years`. A model
        on `members.*.age` therefore validates and then scores nothing, which is
        the rules-versus-payload defect again. Pinned so the day the producer
        is fixed this test starts failing and gets deleted."""
        m = active_model(FeatureCode.DQA_ANOMALY, robust(path="members.*.age", agg="max"))
        svc.attach_model(FeatureCode.DQA_ANOMALY, m, actor="ops")
        svc.set_feature_state(FeatureCode.DQA_ANOMALY, FeatureState.SHADOW, actor="ops", reason="x")
        h = make_household(geo, 5)
        Member.objects.filter(household=h).update(age_years=130)
        out = tasks.score_recent_households_task()
        assert (out["scored"], out["skipped"]) == (0, 1)


class TestRankingFeed:
    @pytest.fixture
    def ranker(self, enabled, db):
        ddup = DdupModelVersion.objects.create(
            version=1, config=model_config(tier3={}), author="a", status="active",
        )
        m = active_model(FeatureCode.DDUP_RANK, linear())
        svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="x")
        return ddup

    def test_the_task_ranks_pending_pairs(self, ranker):
        pair(ranker, "A1", "B1", {"member.surname": 1.0, "member.first_name": 1.0})
        out = tasks.rank_pending_pairs_task()
        assert (out["status"], out["scored"]) == ("ok", 1)

    def test_discovery_finishing_triggers_ranking(self):
        from celery.signals import task_success

        discovery = mock.Mock()
        discovery.name = tasks.DISCOVERY_TASK
        with mock.patch.object(tasks.rank_pending_pairs_task, "delay") as delay:
            task_success.send(sender=discovery, result={})
            delay.assert_called_once_with()

    def test_other_tasks_do_not_trigger_ranking(self):
        from celery.signals import task_success

        other = mock.Mock()
        other.name = "apps.ddup.tasks.auto_merge_high_confidence_pairs_task"
        with mock.patch.object(tasks.rank_pending_pairs_task, "delay") as delay:
            task_success.send(sender=other, result={})
            delay.assert_not_called()


class TestScheduling:
    def test_the_anomaly_feed_is_on_the_beat_schedule(self):
        from nsr_mis.celery import app

        entries = {e["task"]: e for e in app.conf.beat_schedule.values()}
        entry = entries[tasks.ANOMALY_TASK]
        assert entry["schedule"].minute == {45}

    def test_the_ranker_is_chained_not_scheduled(self):
        """A fixed slot could run before discovery finishes."""
        from nsr_mis.celery import app

        assert tasks.RANK_TASK not in {e["task"] for e in app.conf.beat_schedule.values()}

    def test_the_task_names_are_registered_with_celery(self):
        from nsr_mis.celery import app

        app.loader.import_default_modules()
        assert {tasks.RANK_TASK, tasks.ANOMALY_TASK} <= set(app.tasks)

    def test_the_default_batch_size_is_set(self, settings):
        assert settings.AI_ANOMALY_BATCH_SIZE > 0
