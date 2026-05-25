"""CHB-003 — top-k cosine retrieval over ManualChunk."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.embeddings import HashEmbedder
from apps.chatbot.models import ManualChunk
from apps.chatbot.retrieval import retrieve


class RetrievalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        e = HashEmbedder()
        cls.walk_in = ManualChunk.objects.create(
            source_path="steward/walk-in.md",
            heading_path="Walk-in submissions > Fast-track",
            content="Parish Chiefs auto-promote walk-in households via the DIH fast-track lane.",
            embedding=e.embed(
                "Parish Chiefs auto-promote walk-in households via the DIH fast-track lane."
            ),
            token_count=15,
        )
        cls.grievance = ManualChunk.objects.create(
            source_path="steward/grievances.md",
            heading_path="Grievances > Routing",
            content="Grievances are routed to the GRM Officer for triage and resolution.",
            embedding=e.embed("Grievances are routed to the GRM Officer for triage and resolution."),
            token_count=12,
        )
        cls.refdata = ManualChunk.objects.create(
            source_path="admin/refdata.md",
            heading_path="Reference data > Geography",
            content="UBOS publishes the geographic hierarchy that the registry imports.",
            embedding=e.embed(
                "UBOS publishes the geographic hierarchy that the registry imports."
            ),
            token_count=11,
        )

    def test_retrieve_returns_top_k(self):
        hits = retrieve("walk-in households fast-track", k=2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].chunk, self.walk_in)

    def test_retrieve_orders_by_descending_score(self):
        hits = retrieve("grievance routing officer", k=3)
        self.assertEqual(hits[0].chunk, self.grievance)
        # Scores monotonically decrease.
        scores = [h.score for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_retrieve_returns_empty_when_no_chunks(self):
        ManualChunk.objects.all().delete()
        hits = retrieve("anything", k=5)
        self.assertEqual(hits, [])

    def test_retrieve_clamps_to_available_chunks(self):
        hits = retrieve("anything", k=99)
        self.assertEqual(len(hits), 3)
