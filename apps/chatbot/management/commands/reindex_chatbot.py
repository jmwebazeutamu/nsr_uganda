"""Walk docs/user-manual/docs/, chunk + embed every .md, replace ManualChunk.

Replaces (not merges) — the manuals are the source of truth. Re-run
on every deploy where the manual content changes.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.chatbot.chunking import chunk_markdown
from apps.chatbot.embeddings import get_embedder, reset_embedder_cache
from apps.chatbot.models import ManualChunk

DEFAULT_MANUAL_DIR = Path(settings.BASE_DIR) / "docs" / "user-manual" / "docs"


class Command(BaseCommand):
    help = "Re-embed the user manuals into the ManualChunk table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--manual-dir",
            default=str(DEFAULT_MANUAL_DIR),
            help="Directory to walk for .md files (default: docs/user-manual/docs/).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Chunk + count but skip embedding and DB writes.",
        )

    def handle(self, *args, **opts):
        manual_dir = Path(opts["manual_dir"])
        if not manual_dir.is_dir():
            self.stderr.write(self.style.ERROR(f"manual-dir does not exist: {manual_dir}"))
            return

        md_files = sorted(manual_dir.rglob("*.md"))
        if not md_files:
            self.stderr.write(self.style.WARNING(f"no .md files under {manual_dir}"))
            return

        # Build the chunk list first so a dry-run reports the count
        # without ever touching the embedder.
        pending: list[tuple[str, str, str]] = []  # (source_path, heading_path, body)
        for md in md_files:
            rel = md.relative_to(manual_dir).as_posix()
            for ch in chunk_markdown(md.read_text(encoding="utf-8")):
                pending.append((rel, ch.heading_path, ch.body))

        self.stdout.write(f"Chunked {len(md_files)} files into {len(pending)} chunks.")
        if opts["dry_run"]:
            return

        reset_embedder_cache()
        embedder = get_embedder()
        with transaction.atomic():
            ManualChunk.objects.all().delete()
            rows = []
            for source_path, heading_path, body in pending:
                rows.append(
                    ManualChunk(
                        source_path=source_path,
                        heading_path=heading_path,
                        content=body,
                        embedding=embedder.embed(body),
                        token_count=max(1, len(body) // 4),
                    )
                )
            ManualChunk.objects.bulk_create(rows)
        self.stdout.write(self.style.SUCCESS(f"Indexed {len(rows)} chunks."))
