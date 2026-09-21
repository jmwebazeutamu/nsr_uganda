"""What changed between two CSPro instrument versions.

    python manage.py diff_cspro_dictionary wave1.dcf wave2.dcf
    python manage.py diff_cspro_dictionary wave1.dcf wave2.dcf --format json
    python manage.py diff_cspro_dictionary wave1.dcf wave2.dcf --breaking-only

UBOS owns the instrument and delivers it in waves; MGLSD cannot refuse a
wave, so the only defence against a change arriving unnoticed is to read
the dictionary and compare it with the last one (ADR-0034).

Read-only, no database. It parses two files and prints the changeset.
Exit status is 1 when any change needs a human decision, so it can be
wired into a wave-intake script that stops and waits.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.intake.cspro import CsproParseError, parse_dictionary
from apps.intake.cspro_diff import Severity, diff_dictionaries

_ICON = {
    Severity.BREAKING: "BREAKING",
    Severity.REVIEW: "review  ",
    Severity.INFO: "info    ",
}


class Command(BaseCommand):
    help = "Diff two CSPro data dictionaries (.dcf) and classify the changes."

    def add_arguments(self, parser):
        parser.add_argument("old", help="Path to the previously accepted .dcf")
        parser.add_argument("new", help="Path to the incoming wave's .dcf")
        parser.add_argument("--format", choices=("text", "json"), default="text")
        parser.add_argument(
            "--breaking-only", action="store_true",
            help="Print only the changes that need a decision.",
        )

    def _load(self, path: str):
        p = Path(path)
        if not p.is_file():
            raise CommandError(f"no such file: {path}")
        try:
            # CSPro writes UTF-8 with a BOM, and older tools write
            # Latin-1. Neither should stop a wave being reviewed.
            return parse_dictionary(p.read_text(encoding="utf-8-sig"))
        except UnicodeDecodeError:
            return parse_dictionary(p.read_text(encoding="latin-1"))
        except CsproParseError as exc:
            raise CommandError(f"{path}: {exc}") from exc

    def handle(self, *args, **options):
        diff = diff_dictionaries(self._load(options["old"]), self._load(options["new"]))
        changes = diff.breaking if options["breaking_only"] else diff.sorted_changes()

        if options["format"] == "json":
            self.stdout.write(json.dumps({
                "old_version": diff.old_version,
                "new_version": diff.new_version,
                "counts": diff.counts(),
                "is_clean": diff.is_clean,
                "changes": [
                    {**asdict(c), "severity": str(c.severity)} for c in changes
                ],
            }, indent=2))
            return 1 if not diff.is_clean else None

        counts = diff.counts()
        self.stdout.write(
            f"{diff.old_version} -> {diff.new_version}: "
            f"{counts['breaking']} needing a decision, "
            f"{counts['review']} to review, {counts['info']} informational.\n",
        )

        if not changes:
            self.stdout.write(self.style.SUCCESS(
                "No differences." if not diff
                else "Nothing needing a decision.",
            ))
            return None

        for change in changes:
            style = (self.style.ERROR if change.severity is Severity.BREAKING
                     else self.style.WARNING if change.severity is Severity.REVIEW
                     else self.style.SUCCESS)
            self.stdout.write(style(f"  {_ICON[change.severity]}  {change.summary}"))
            if change.old or change.new:
                self.stdout.write(
                    f"              {change.old or '(none)'}  ->  {change.new or '(none)'}",
                )
            if change.detail:
                for line in _wrap(change.detail, 68):
                    self.stdout.write(f"              {line}")
            self.stdout.write("")

        if not diff.is_clean:
            self.stdout.write(self.style.ERROR(
                f"{counts['breaking']} change(s) need a decision before this "
                "wave's data can be interpreted. Nothing here may be resolved "
                "by picking the nearest matching code — where there is no "
                "equivalent, record that there is none.",
            ))
            sys.exit(1)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
