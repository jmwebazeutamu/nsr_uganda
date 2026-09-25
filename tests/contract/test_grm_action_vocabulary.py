"""The console and the server name the same actions.

`allowed_actions` exists so the console stops keeping its own copy of
the GRM state machine: the workbench offered "Assign to me" on a closed
case and the server refused it, because the two had drifted. The
serializer answers what the case will accept and the console renders
that answer.

Which only works while both sides spell the actions the same way. A
console asking `_grmAllows(current, "add-task")` against a server that
says "add_task" gets false for every case and the button silently
disappears — the original defect wearing the fix's clothes. This is the
project's recurring failure mode (see the two-vocabularies note in
CLAUDE.md's neighbours), and only a paired test catches it.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from apps.grievance import visibility

CONSOLE = Path("design/v0.1/screens/screens-grm.jsx")


def server_vocabulary() -> set[str]:
    """Every action name allowed_actions can return."""
    source = inspect.getsource(visibility.allowed_actions)
    return set(re.findall(r'actions\.append\("([a-z_]+)"\)', source)) | set(
        re.findall(r'actions = \["([a-z_]+)"\]', source),
    )


def console_vocabulary() -> set[str]:
    text = CONSOLE.read_text()
    return set(re.findall(r'_grmAllows\([^,]+,\s*"([a-z_]+)"\)', text))


class TestTheyAgree:

    def test_the_server_has_a_vocabulary_at_all(self):
        # A regex that stops matching would make every case below pass
        # vacuously, which is how sweeps like this go wrong.
        vocabulary = server_vocabulary()
        assert len(vocabulary) >= 5, vocabulary
        assert "assign" in vocabulary

    def test_the_console_asks_about_actions_the_server_knows(self):
        unknown = console_vocabulary() - server_vocabulary()
        assert unknown == set(), (
            f"the console gates buttons on {sorted(unknown)}, which "
            "allowed_actions never returns — those buttons are hidden for "
            "every case, permanently and silently"
        )

    def test_the_console_actually_uses_it(self):
        asked = console_vocabulary()
        assert {"assign", "escalate", "resolve", "close"} <= asked, (
            f"only {sorted(asked)} are gated on the server's answer; the "
            "rest are a second copy of the state machine"
        )

    def test_the_console_no_longer_derives_those_from_status(self):
        """The literal comparisons the buttons used to be built from."""
        text = CONSOLE.read_text()
        # Strip comments — the removals are documented in them.
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = "\n".join(
            re.sub(r"(^|\s)//.*$", r"\1", line) for line in code.split("\n")
        )
        for gone in (
            'current.status !== "resolved" && current.status !== "closed" && current.tier',
            'current.status === "resolved" && (\n                  <button',
        ):
            assert gone not in code, f"still deriving a button from status: {gone!r}"


@pytest.mark.django_db
class TestAddTaskIsInTheAnswer:
    """The Add-task button was gated on `status !== resolved && status
    !== closed` — the service's rule, written out again in JSX."""

    def _case(self):
        from apps.grievance.services import open_grievance

        return open_grievance(category="other", description="x")

    def test_an_open_case_accepts_a_task(self):
        assert "add_task" in visibility.allowed_actions(self._case())

    def test_a_resolved_case_does_not(self):
        from apps.grievance.services import resolve

        g = self._case()
        resolve(g, actor="officer", narrative="done, nothing outstanding")
        assert "add_task" not in visibility.allowed_actions(g)

    def test_the_answer_matches_what_create_task_does(self):
        """Pins the two together rather than trusting them to agree."""
        from apps.grievance.assignees import IneligibleAssignee
        from apps.grievance.services import GrievanceError, create_task, resolve

        g = self._case()
        resolve(g, actor="officer", narrative="done, nothing outstanding")
        assert "add_task" not in visibility.allowed_actions(g)
        with pytest.raises((GrievanceError, IneligibleAssignee)) as exc:
            create_task(g, title="t", description="", assigned_to="whoever",
                        actor="officer")
        assert "resolved" in str(exc.value) or "not an active" in str(exc.value)
