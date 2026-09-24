"""The remediation reassigns what is live and annotates what is not.

Rewriting the assignee on a closed, placeholder-filled record would put
a real operator's name against a task titled "Test Test". The phantom
at least implicates nobody. So closed test records keep their assignee
and gain a note; only live work moves.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.grievance.management.commands import remediate_phantom_assignees as cmd
from apps.grievance.models import Grievance, GrievanceStatus
from apps.grievance.services import open_grievance

pytestmark = pytest.mark.django_db

LIVE_ID = next(iter(cmd.REASSIGN))
LIVE_OWNER = cmd.REASSIGN[LIVE_ID]
ANNOTATE_IDS = list(cmd.ANNOTATE)


def _run(*args):
    out = StringIO()
    call_command("remediate_phantom_assignees", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def owner(django_user_model):
    """The account the live case is moved onto.

    On production this is an nsr_admin with a national scope, which is
    why the remediation could run at all — assignment now checks that
    the target's role carries the tier and that their scope reaches
    the household (QA P2.10). The fixture says so rather than relying
    on a bare user that the service would refuse.
    """
    from django.contrib.auth.models import Group

    from apps.security.models import OperatorScope, ScopeLevel

    user = django_user_model.objects.create_user(
        username=LIVE_OWNER, password="p", email="owner@example.test",
    )
    user.groups.add(Group.objects.get_or_create(name="nsr_admin")[0])
    OperatorScope.objects.get_or_create(
        user=user, scope_level=ScopeLevel.NATIONAL, scope_code="",
    )
    return user


@pytest.fixture
def records(db):
    """The three grievances, as production holds them."""
    live = open_grievance(
        category="operator_conduct", description="real complaint",
    )
    Grievance.objects.filter(pk=live.pk).update(
        id=LIVE_ID, assigned_to="Twikirize J. · District M&E",
        status=GrievanceStatus.IN_PROGRESS,
    )
    made = {}
    for gid in ANNOTATE_IDS:
        g = open_grievance(category="other", description="Quia ullam omnis ut")
        Grievance.objects.filter(pk=g.pk).update(
            id=gid, assigned_to="Adong Florence · CDO Tapac",
            status=GrievanceStatus.CLOSED,
        )
        made[gid] = gid
    return Grievance.objects.get(id=LIVE_ID), made


def test_dry_run_writes_nothing(records, owner):
    output = _run()

    assert "Dry run" in output
    assert Grievance.objects.get(id=LIVE_ID).assigned_to.startswith("Twikirize")
    assert Grievance.objects.get(id=ANNOTATE_IDS[0]).comments.count() == 0


def test_apply_requires_an_actor(records, owner):
    with pytest.raises(CommandError, match="--actor is required"):
        _run("--apply")


def test_the_live_grievance_moves_to_a_real_user(records, owner):
    _run("--apply", "--actor", "ops")

    assert Grievance.objects.get(id=LIVE_ID).assigned_to == LIVE_OWNER


def test_the_reassignment_says_what_it_replaced(records, owner):
    _run("--apply", "--actor", "ops")

    note = Grievance.objects.get(id=LIVE_ID).comments.last().body
    assert "Twikirize J. · District M&E" in note
    assert "never a user account" in note


def test_closed_test_records_keep_their_assignee(records, owner):
    """Who held a closed case is audit history, not a live pointer."""
    _run("--apply", "--actor", "ops")

    for gid in ANNOTATE_IDS:
        g = Grievance.objects.get(id=gid)
        assert g.assigned_to == "Adong Florence · CDO Tapac", gid
        assert g.status == GrievanceStatus.CLOSED, gid


def test_closed_test_records_gain_a_note_that_explains_them(records, owner):
    _run("--apply", "--actor", "ops")

    for gid in ANNOTATE_IDS:
        body = Grievance.objects.get(id=gid).comments.last().body
        assert "18 May 2026" in body
        assert "Nothing is outstanding" in body


def test_rerunning_annotates_nothing_twice(records, owner):
    _run("--apply", "--actor", "ops")
    counts = {
        gid: Grievance.objects.get(id=gid).comments.count()
        for gid in ANNOTATE_IDS
    }

    output = _run("--apply", "--actor", "ops")

    assert "already annotated" in output
    for gid, before in counts.items():
        assert Grievance.objects.get(id=gid).comments.count() == before


def test_a_record_already_on_a_real_user_is_left_alone(records, owner,
                                                       django_user_model):
    """Somebody tidying up by hand must not be undone by a re-run."""
    other = django_user_model.objects.create_user(
        username="someone-real", password="p", email="s@example.test",
    )
    Grievance.objects.filter(id=LIVE_ID).update(assigned_to=other.username)

    output = _run("--apply", "--actor", "ops")

    assert "leaving alone" in output
    assert Grievance.objects.get(id=LIVE_ID).assigned_to == other.username
