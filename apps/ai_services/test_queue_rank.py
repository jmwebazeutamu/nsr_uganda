"""ADR-0045 — the reviewer's dedup queue and the advisory rank.

The queue endpoint is what reviewers use. It may carry a rank only while the
feature is ADVISORY; in shadow, off, or after the kill switch it must carry
none, however many suggestions are stored.
"""

import pytest
from rest_framework.test import APIClient

from apps.ai_services import services as svc
from apps.ai_services.ddup_ranking import rank_pending_pairs
from apps.ai_services.models import AiFeature, AiSuggestion, FeatureCode, FeatureState
from apps.ai_services.tests import active_model, linear, pair
from apps.ddup.models import DdupModelVersion
from apps.ddup.tests import model_config

pytestmark = pytest.mark.django_db

URL = "/api/v1/ddup/match-pairs/?status=pending"
SURNAME, FIRST = "member.surname", "member.first_name"


@pytest.fixture
def client(django_user_model):
    u = django_user_model.objects.create_user(username="rev", password="p", is_superuser=True)
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def ranked(settings, db):
    """Three pending pairs, ranked, feature left in SHADOW."""
    settings.AI_SERVICES_ENABLED = True
    ddup = DdupModelVersion.objects.create(version=1, config=model_config(tier3={}), author="a", status="active")
    m = active_model(FeatureCode.DDUP_RANK, linear())
    svc.attach_model(FeatureCode.DDUP_RANK, m, actor="ops")
    svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.SHADOW, actor="ops", reason="measure")
    pairs = {n: pair(ddup, f"A{n}", f"B{n}", {SURNAME: s, FIRST: s})
             for n, s in (("lo", 0.2), ("hi", 1.0), ("mid", 0.6))}
    rank_pending_pairs()
    return pairs


def go_advisory():
    AiFeature.objects.filter(code=FeatureCode.DDUP_RANK).update(state=FeatureState.ADVISORY)


def rows(client, extra=""):
    r = client.get(URL + extra)
    assert r.status_code == 200, r.content
    body = r.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


class TestNothingLeaksBeforeAdvisory:
    def test_shadow_carries_no_rank(self, client, ranked):
        for r in rows(client, "&order=ai"):
            assert r["ai_rank"] is None

    def test_shadow_ignores_the_ordering_request(self, client, ranked):
        plain = [r["id"] for r in rows(client)]
        asked = [r["id"] for r in rows(client, "&order=ai")]
        assert asked == plain

    def test_the_kill_switch_removes_it_again(self, client, ranked):
        go_advisory()
        assert all(r["ai_rank"] is not None for r in rows(client))
        svc.set_feature_state(FeatureCode.DDUP_RANK, FeatureState.OFF, actor="ops", reason="incident")
        assert all(r["ai_rank"] is None for r in rows(client))

    def test_the_master_switch_removes_it(self, client, ranked, settings):
        go_advisory()
        settings.AI_SERVICES_ENABLED = False
        assert all(r["ai_rank"] is None for r in rows(client, "&order=ai"))


class TestAdvisory:
    def test_each_pair_carries_its_score(self, client, ranked):
        go_advisory()
        scores = {r["id"]: r["ai_rank"]["score"] for r in rows(client)}
        assert scores[ranked["hi"].id] > scores[ranked["mid"].id] > scores[ranked["lo"].id]

    def test_order_ai_puts_the_likeliest_duplicates_first(self, client, ranked):
        go_advisory()
        ids = [r["id"] for r in rows(client, "&order=ai")]
        assert ids == [ranked[n].id for n in ("hi", "mid", "lo")]

    def test_without_the_parameter_the_default_order_is_untouched(self, client, ranked):
        go_advisory()
        assert [r["id"] for r in rows(client)] == [r["id"] for r in rows(client)]
        newest_first = sorted(ranked.values(), key=lambda p: p.created_at, reverse=True)
        assert [r["id"] for r in rows(client)] == [p.id for p in newest_first]

    def test_unranked_pairs_sort_last_not_first(self, client, ranked, settings):
        go_advisory()
        ddup = DdupModelVersion.objects.get(status="active")
        new = pair(ddup, "Anew", "Bnew", {SURNAME: 1.0, FIRST: 1.0})
        ids = [r["id"] for r in rows(client, "&order=ai")]
        assert ids[-1] == new.id
        assert next(r for r in rows(client, "&order=ai") if r["id"] == new.id)["ai_rank"] is None

    def test_the_newest_suggestion_for_a_pair_wins(self, client, ranked):
        go_advisory()
        run = rank_pending_pairs()
        AiSuggestion.objects.filter(run=run, subject_id=ranked["lo"].id).update(score=0.99)
        lo = next(r for r in rows(client) if r["id"] == ranked["lo"].id)
        assert lo["ai_rank"]["score"] == pytest.approx(0.99)

    def test_the_rank_is_a_score_and_a_model_not_personal_data(self, client, ranked):
        go_advisory()
        assert set(rows(client)[0]["ai_rank"]) == {"score", "model"}

    def test_it_costs_one_query_however_many_pairs(self, client, ranked, django_assert_max_num_queries):
        go_advisory()
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            rows(client, "&order=ai")
        ddup = DdupModelVersion.objects.get(status="active")
        for i in range(10):
            pair(ddup, f"Ax{i}", f"Bx{i}", {SURNAME: 0.5, FIRST: 0.5})
        rank_pending_pairs()
        with CaptureQueriesContext(connection) as big:
            rows(client, "&order=ai")
        assert len(big) == len(small)
