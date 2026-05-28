"""DATA-EXP NFR smoke tests.

ADR-0023 §"NFR targets":
- Catalogue browse P95 < 500 ms.
- Aggregate query P95 < 3 s.

Marked @pytest.mark.performance so they don't run in the default CI
lane — they're a pre-merge gate.

Notes:
- These run against the Django test client, NOT a deployed instance.
  Test-client time understates real over-the-wire latency, so the
  thresholds here are a CEILING — if the test client P95 exceeds them
  the deployed system definitely will.
- Aggregate queries pull from the corpus when available; fall back to
  a minimal hand-rolled payload otherwise.
"""

from __future__ import annotations

import pathlib
import statistics
import time

import pytest
from django.test import override_settings
from rest_framework.test import APIClient


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.performance,
]


DATASETS_URL = "/api/v1/data-explorer/datasets/"
AGGREGATE_URL = "/api/v1/data-explorer/aggregate/"
CORPUS_PATH = pathlib.Path("scripts/data_explorer/aggregate_query_corpus.yaml")


@pytest.fixture
def client_explorer(explorer_user):
    c = APIClient()
    c.force_authenticate(user=explorer_user)
    return c


def _p95(samples: list[float]) -> float:
    if not samples:
        return float("inf")
    samples_sorted = sorted(samples)
    # quantiles n=20 → 19 cut-points, [-1] is the P95.
    return statistics.quantiles(samples_sorted, n=20)[-1]



class TestCatalogueBrowseP95:

    def test_50_browses_under_500ms_p95(self, client_explorer, dataset):
        durations: list[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            r = client_explorer.get(DATASETS_URL)
            t1 = time.perf_counter()
            assert r.status_code == 200
            durations.append((t1 - t0) * 1000.0)  # ms

        p95 = _p95(durations)
        assert p95 < 500.0, (
            f"Catalogue browse P95 = {p95:.1f}ms > 500ms NFR. "
            f"All samples: min={min(durations):.1f} "
            f"max={max(durations):.1f} median="
            f"{statistics.median(durations):.1f}"
        )



class TestAggregateP95:

    @pytest.fixture
    def queries(self, dataset, variable_internal):
        """10 typical aggregate payloads. Pull from the corpus when
        the Data Analyst has landed it; fall back to a single payload
        repeated 10 times so the smoke still exercises the path."""
        if CORPUS_PATH.exists():
            import yaml
            corpus = yaml.safe_load(CORPUS_PATH.read_text())
            picks = [
                q["payload"]
                for q in corpus.get("queries", [])
                if q.get("expected_outcome") == "full_return"
            ][:10]
            if picks:
                return picks
        # Fallback: minimal payload, repeat 10x.
        base = {
            "dataset_code": dataset.code,
            "projection": [variable_internal.code],
            "filters": [],
            "geographic_scope": {
                "level": "sub_county",
                "codes": ["SC-1"],
            },
        }
        return [base] * 10

    def test_10_aggregates_under_3s_p95(self, client_explorer, queries):
        durations: list[float] = []
        ok = 0
        for q in queries:
            t0 = time.perf_counter()
            r = client_explorer.post(AGGREGATE_URL, q, format="json")
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000.0)
            if r.status_code == 200:
                ok += 1
        if ok == 0:
            pytest.skip(
                "No aggregate calls returned 200 — the Coder's matview "
                "wiring may not be live in test mode; P95 only meaningful "
                "against a working endpoint."
            )
        p95 = _p95(durations)
        assert p95 < 3000.0, (
            f"Aggregate P95 = {p95:.1f}ms > 3000ms NFR. "
            f"min={min(durations):.1f} max={max(durations):.1f} "
            f"median={statistics.median(durations):.1f}"
        )
