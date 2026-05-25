"""CHB-003 — reindex_chatbot management command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from apps.chatbot.models import ManualChunk


class ReindexCommandTests(TestCase):
    def _write_manual(self, root: Path, rel: str, body: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_indexes_chunks_from_markdown_tree(self):
        from django.conf import settings

        manual_root = Path(settings.BASE_DIR) / "test_manual_tmp"
        manual_root.mkdir(parents=True, exist_ok=True)
        try:
            self._write_manual(
                manual_root,
                "steward/walk-in.md",
                "# Walk-in\n\n## Fast-track\n\nParish Chiefs auto-promote.\n",
            )
            self._write_manual(
                manual_root,
                "field/grievances.md",
                "# Grievances\n\n## Routing\n\nGo to GRM Officer.\n",
            )
            out = StringIO()
            call_command("reindex_chatbot", manual_dir=str(manual_root), stdout=out)
            self.assertIn("Indexed 2 chunks", out.getvalue())
            self.assertEqual(ManualChunk.objects.count(), 2)
            paths = set(ManualChunk.objects.values_list("source_path", flat=True))
            self.assertEqual(paths, {"steward/walk-in.md", "field/grievances.md"})
        finally:
            import shutil

            shutil.rmtree(manual_root, ignore_errors=True)

    def test_replaces_existing_chunks(self):
        from django.conf import settings

        from apps.chatbot.embeddings import HashEmbedder

        # Seed an old row that should be wiped.
        ManualChunk.objects.create(
            source_path="old.md",
            heading_path="old",
            content="old content",
            embedding=HashEmbedder().embed("old content"),
            token_count=2,
        )
        manual_root = Path(settings.BASE_DIR) / "test_manual_tmp"
        manual_root.mkdir(parents=True, exist_ok=True)
        try:
            self._write_manual(
                manual_root, "new.md", "# New\n\n## S\n\nNew body.\n"
            )
            call_command("reindex_chatbot", manual_dir=str(manual_root), stdout=StringIO())
            self.assertEqual(ManualChunk.objects.count(), 1)
            self.assertEqual(ManualChunk.objects.first().source_path, "new.md")
        finally:
            import shutil

            shutil.rmtree(manual_root, ignore_errors=True)

    def test_dry_run_does_not_write(self):
        from django.conf import settings

        manual_root = Path(settings.BASE_DIR) / "test_manual_tmp"
        manual_root.mkdir(parents=True, exist_ok=True)
        try:
            self._write_manual(
                manual_root, "x.md", "# X\n\n## A\n\nA-body.\n\n## B\n\nB-body.\n"
            )
            out = StringIO()
            call_command(
                "reindex_chatbot",
                manual_dir=str(manual_root),
                dry_run=True,
                stdout=out,
            )
            self.assertIn("Chunked 1 files into 2 chunks", out.getvalue())
            self.assertEqual(ManualChunk.objects.count(), 0)
        finally:
            import shutil

            shutil.rmtree(manual_root, ignore_errors=True)
