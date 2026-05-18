"""US-S20-001 — PII lint for constraint and skip-logic messages.

Constraint / hint / label text is shown to respondents AND lands
verbatim in DqaResult error rows that the violations dashboard
displays alongside the record. A common authoring mistake is
embedding a "real-looking" example value in the message — e.g.
"Enter a NIN like CM12345678ABCDE" or "Phone must look like
+256770123456". Those examples are NOT operational data but they
trickle into logs, screenshots, and dashboards. If the example
happens to MATCH a real person's NIN/phone, the leak is real.

This module flags author-time PII shapes. It does not block save —
the admin surfaces violations as warnings so the author can
shorten the example to a placeholder ("CMxxxxxxxxxxxx") if the
flag is a false positive.

Returned violation shape:
    {
      "rule": "nin" | "phone" | "email" | "long_digits" | "id_card",
      "matched": "<the substring that tripped the rule>",
      "where": "<the field name, e.g. constraint_message>",
    }

Not exhaustive — these are the high-signal Uganda + general
patterns the field instrument is most likely to leak. Extend
list as new PII shapes show up in the DPO's anomaly feed.
"""

from __future__ import annotations

import re

# Uganda NIN: format is 14 alphanumeric chars starting with a letter
# (typically CM/CF for male/female). The legacy XLSForm constraint
# accepts 10-20 alphanumerics; we use the same liberal range so the
# lint catches anything that LOOKS like a NIN even if not strictly
# 14-char. Boundary requires non-alphanumeric on each side so we
# don't fire on "ABCDEFGHIJKL" appearing inside an unrelated word.
_NIN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]{9,19}(?![A-Za-z0-9])")

# Uganda phone numbers: 0[0-9]{9} or +256[0-9]{9} or 256[0-9]{9}.
# Allows optional spaces / dashes inside.
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?256[\s\-]?|0)[0-9]{9}(?!\d)",
)

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# A run of 11+ digits anywhere — covers passports, voter cards,
# foreign IDs, MM wallet numbers. 10 was too noisy (catches
# percentages, large counters).
_LONG_DIGITS_PATTERN = re.compile(r"(?<!\d)\d{11,}(?!\d)")

# Plate-like sequences: 3 letters + 3 digits, e.g. UAE 123J or UAB123J.
# Cheap heuristic for vehicle plates; few false positives.
_PLATE_PATTERN = re.compile(r"(?<![A-Za-z0-9])U[A-Z]{2}[\s\-]?\d{3}[A-Z](?![A-Za-z0-9])")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Phone first so a phone-shaped number doesn't get classified as
    # `long_digits` ("256770123456" is 12 digits — phone, not generic).
    ("phone", _PHONE_PATTERN),
    ("email", _EMAIL_PATTERN),
    ("plate", _PLATE_PATTERN),
    ("nin", _NIN_PATTERN),
    ("long_digits", _LONG_DIGITS_PATTERN),
)


def lint_text(text: str, *, where: str = "text") -> list[dict]:
    """Scan a single string for PII shapes. Returns one violation
    per match. Empty list when clean. `where` is echoed back so the
    admin can show which field tripped."""
    if not text:
        return []
    violations: list[dict] = []
    consumed_spans: list[tuple[int, int]] = []

    def _overlaps_consumed(start: int, end: int) -> bool:
        for cs, ce in consumed_spans:
            if start < ce and end > cs:
                return True
        return False

    for rule, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if _overlaps_consumed(m.start(), m.end()):
                continue  # already attributed to a higher-priority rule
            violations.append({
                "rule": rule,
                "matched": m.group(0),
                "where": where,
            })
            consumed_spans.append((m.start(), m.end()))
    return violations


def lint_form_constraint(constraint) -> list[dict]:
    """FormConstraint.message + .description. Returns a flat list of
    violations across the two fields."""
    out = []
    out.extend(lint_text(constraint.message or "", where="message"))
    out.extend(lint_text(constraint.description or "", where="description"))
    return out


def lint_form_question(question) -> list[dict]:
    """FormQuestion.label + .hint + .constraint_message. Hint and
    label are respondent-facing; constraint_message lands in DQA
    error rows. All three are PII surfaces."""
    out = []
    out.extend(lint_text(question.label or "", where="label"))
    out.extend(lint_text(question.hint or "", where="hint"))
    out.extend(lint_text(
        question.constraint_message or "", where="constraint_message",
    ))
    return out


def lint_form_version(form_version) -> dict:
    """Walk the whole authored form (sections → questions →
    constraints). Returns a structured report keyed by question
    name for surfaces (admin + future scan command)."""
    report: dict = {"violations": [], "questions_scanned": 0}
    for section in form_version.sections.prefetch_related(
        "questions__constraints",
    ).all():
        for q in section.questions.all():
            report["questions_scanned"] += 1
            q_violations = lint_form_question(q)
            for c in q.constraints.all():
                q_violations.extend(lint_form_constraint(c))
            if q_violations:
                report["violations"].append({
                    "section": section.code, "question": q.name,
                    "items": q_violations,
                })
    return report
