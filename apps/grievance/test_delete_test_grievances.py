"""Deleting the demo records, and refusing when they are not what they were."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.grievance.management.commands import delete_test_grievances as cmd
from apps.grievance.models import Grievance, GrievanceStatus, GrievanceTask
from apps.grievance.services import open_grievance
from apps.security.models import AuditEvent

pytestmark = pytest.mark.django_db

IDS = list(cmd.EXPECTED)


def _run(*args):
    out = StringIO()
    call_command("delete_test_grievances", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def demo_records(db, django_user_model):
    made = []
    for gid, status in cmd.EXPECTED.items():
        g = open_grievance(category="other", description="Quia ullam omnis ut")
        Grievance.objects.filter(pk=g.pk).update(
            id=gid, status=status,
            assigned_to="Adong Florence · CDO Tapac",
        )
        g = Grievance.objects.get(id=gid)
        GrievanceTask.objects.create(
            grievance=g, title="Ut et proident unde",
            assigned_to="Inventore consequunt", created_by="x",
        )
        # open_grievance audited the id it generated, which the line
        # above replaced — so emit one against the id the record
        # actually carries, the way production's history does.
        from apps.security.audit import emit as _emit
        _emit("create", "grievance", gid, actor="demo-run",
              reason="18 May 2026 demo")
        made.append(g)
    return made


def test_dry_run_deletes_nothing(demo_records):
    output = _run()

    assert "Dry run" in output
    assert Grievance.objects.filter(id__in=IDS).count() == 2


def test_apply_requires_an_actor(demo_records):
    with pytest.raises(CommandError, match="--actor is required"):
        _run("--apply")


def test_the_grievances_and_their_tasks_go(demo_records):
    _run("--apply", "--actor", "ops")

    assert not Grievance.objects.filter(id__in=IDS).exists()
    assert not GrievanceTask.objects.filter(grievance_id__in=IDS).exists()


def test_the_deletion_is_audited_with_what_was_removed(demo_records):
    """The chain has to say where they went, and what they were."""
    _run("--apply", "--actor", "ops")

    for gid in IDS:
        event = AuditEvent.objects.filter(
            action="delete", entity_type="grievance", entity_id=gid,
        ).first()
        assert event is not None, gid
        assert event.actor_id == "ops"
        assert event.field_changes["assigned_to"] == "Adong Florence · CDO Tapac"
        assert event.field_changes["task_ids"], "task ids not recorded"


def test_audit_events_about_them_survive_the_delete(demo_records):
    """AuditEvent references entities by string id, not FK — the record
    of what happened does not depend on the thing it happened to."""
    before = AuditEvent.objects.filter(entity_id__in=IDS).count()
    assert before > 0

    _run("--apply", "--actor", "ops")

    assert AuditEvent.objects.filter(entity_id__in=IDS).count() >= before


def test_it_refuses_when_a_record_has_moved(demo_records):
    """A reopened grievance is not the record this was written for."""
    Grievance.objects.filter(id=IDS[0]).update(status=GrievanceStatus.OPEN)

    with pytest.raises(CommandError, match="the records have changed"):
        _run("--apply", "--actor", "ops")

    assert Grievance.objects.filter(id__in=IDS).count() == 2


def test_it_refuses_when_somebody_real_has_taken_it_on(
    demo_records, django_user_model,
):
    django_user_model.objects.create_user(username="real-person", password="p")
    Grievance.objects.filter(id=IDS[1]).update(assigned_to="real-person")

    with pytest.raises(CommandError, match="the records have changed"):
        _run("--apply", "--actor", "ops")

    assert Grievance.objects.filter(id__in=IDS).count() == 2


def test_rerunning_is_a_no_op(demo_records):
    _run("--apply", "--actor", "ops")
    assert "Nothing to delete" in _run("--apply", "--actor", "ops")
