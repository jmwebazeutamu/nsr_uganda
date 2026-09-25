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


@pytest.mark.django_db
class TestABulkActionRefusesPerRow:
    """QA P1.1. The console fans a bulk action out to one POST per
    grievance and reports what came back. That only works if each
    refusal carries a reason a person can act on — a bare 400 gives the
    operator a list of ids and nothing to do about them.

    And the console predicts which rows will refuse from
    allowed_actions, so these two have to agree: a prediction that is
    wrong in the permissive direction is a dialog that promises twelve
    and delivers seven.
    """

    def _client(self, django_user_model):
        from django.contrib.auth.models import Group
        from rest_framework.test import APIClient

        from apps.security.models import OperatorScope, ScopeLevel

        user = django_user_model.objects.create_user(
            username="bulk.operator", password="p",
        )
        user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
        OperatorScope.objects.get_or_create(
            user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _mixed(self):
        """One open case and one resolved one — the everyday selection
        somebody ticks before pressing Close."""
        from apps.grievance.services import open_grievance, resolve

        still_open = open_grievance(category="other", description="open one")
        resolved = open_grievance(category="other", description="resolved one")
        resolve(resolved, actor="officer", narrative="Sorted at the parish")
        return still_open, resolved

    def test_the_refusal_says_what_was_wrong(self, django_user_model):
        still_open, _resolved = self._mixed()
        client = self._client(django_user_model)

        r = client.post(
            f"/api/v1/grm/grievances/{still_open.id}/close/",
            {"narrative": "Closing the batch"}, format="json",
        )
        assert r.status_code == 400
        detail = r.data["detail"]
        assert detail and not detail.isdigit(), (
            "the console renders this string next to the id; a bare "
            "status code gives the operator nothing to act on"
        )

    def test_the_eligible_row_still_goes_through(self, django_user_model):
        """Per-row, not all-or-nothing: one bad row must not stop the
        rest, or a mixed selection could never be actioned."""
        from apps.grievance.models import GrievanceStatus

        still_open, resolved = self._mixed()
        client = self._client(django_user_model)

        for grievance in (still_open, resolved):
            client.post(
                f"/api/v1/grm/grievances/{grievance.id}/close/",
                {"narrative": "Closing the batch"}, format="json",
            )

        still_open.refresh_from_db()
        resolved.refresh_from_db()
        assert still_open.status == GrievanceStatus.OPEN
        assert resolved.status == GrievanceStatus.CLOSED

    def test_allowed_actions_predicts_the_refusal(self, django_user_model):
        """What the console disables the button on. If this said
        "close" for an open case, the button would be live and every
        row would come back refused — which is the defect."""
        still_open, resolved = self._mixed()
        assert "close" not in visibility.allowed_actions(still_open)
        assert "close" in visibility.allowed_actions(resolved)

    def test_the_prediction_is_not_permissive(self, django_user_model):
        """Every action allowed_actions offers for a case is one the
        API accepts. The other direction is allowed to be
        conservative; this one is not, because it is what the console
        promises."""
        from apps.grievance.models import GrievanceStatus

        still_open, resolved = self._mixed()
        client = self._client(django_user_model)

        for grievance, action, body in [
            (resolved, "close", {"narrative": "Grace period elapsed"}),
        ]:
            assert action in visibility.allowed_actions(grievance)
            r = client.post(
                f"/api/v1/grm/grievances/{grievance.id}/{action}/",
                body, format="json",
            )
            assert r.status_code == 200, (
                f"allowed_actions offered {action!r} and the API refused "
                f"it: {r.data}"
            )
        resolved.refresh_from_db()
        assert resolved.status == GrievanceStatus.CLOSED
