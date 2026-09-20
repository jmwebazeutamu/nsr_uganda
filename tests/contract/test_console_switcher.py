"""You must be able to get from one console to the other.

The operator console and the Admin Console are separate pages served by
separate views. Neither linked to the other: once in either one the only
way across was the masthead to `/home/`, or typing the URL. Both
shells now carry a switcher in the topbar.

The operator-side link is gated, because `/admin-console/` answers 403
to anyone outside five groups. A link shown to a user the server will
refuse is worse than no link — it reads as a permission they have. The
gate is duplicated in JavaScript out of necessity, so these cases hold
the two copies to the same list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from apps.admin_console.permissions import ADMIN_CONSOLE_GROUPS

REPO = Path(__file__).resolve().parent.parent.parent
DESIGN = REPO / "design"
API_CLIENT = DESIGN / "v0.1" / "data" / "api-client.jsx"
OPERATOR_SHELL = DESIGN / "app.jsx"
ADMIN_SHELL = DESIGN / "v0.1" / "screens" / "app-admin.jsx"

pytestmark = pytest.mark.django_db


def _js_group_list() -> list[str]:
    src = API_CLIENT.read_text()
    block = re.search(
        r"const NSR_ADMIN_CONSOLE_GROUPS = \[(.*?)\];", src, re.S,
    )
    assert block, "the console no longer declares NSR_ADMIN_CONSOLE_GROUPS"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_the_two_gates_admit_the_same_groups():
    """The console decides whether to show the link; the view decides
    whether to serve the page. They have to agree."""
    assert sorted(_js_group_list()) == sorted(ADMIN_CONSOLE_GROUPS)


def test_the_operator_shell_links_to_the_admin_console():
    src = OPERATOR_SHELL.read_text()
    assert 'href="/admin-console/"' in src
    # Gated on the same rule the server applies.
    assert "nsrCanAdminConsole(me)" in src


def test_the_admin_shell_links_back():
    src = ADMIN_SHELL.read_text()
    assert 'href="/console/"' in src


def test_both_links_are_anchors_not_click_handlers():
    """A real navigation between two pages. An anchor is keyboard
    reachable, middle-clickable and shows its target; an onClick is
    none of those."""
    for shell, href in (
        (OPERATOR_SHELL, "/admin-console/"),
        (ADMIN_SHELL, "/console/"),
    ):
        src = shell.read_text()
        assert re.search(rf'<a[^>]*href="{re.escape(href)}"', src), (
            f"{shell.name} no longer reaches {href} with an anchor"
        )


# --- the links have to point somewhere the user can actually go ------------

def _user(username, *, groups=(), superuser=False):
    user_model = get_user_model()
    user = user_model.objects.create_user(username, password="x")
    if superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    client = Client()
    assert client.login(username=username, password="x")
    return client


@pytest.mark.parametrize("group", ADMIN_CONSOLE_GROUPS)
def test_each_admitted_group_can_open_the_admin_console(group):
    client = _user(f"admin-{group}".lower().replace("_", "-"), groups=[group])
    assert client.get("/admin-console/").status_code == 200


def test_an_admin_can_also_reach_the_operator_console():
    """The admin-side link is ungated because this is always true."""
    client = _user("both-ways", groups=["nsr_admin"])
    assert client.get("/console/").status_code == 200


def test_an_operator_outside_those_groups_is_refused():
    """Which is why the operator-side link is hidden for them rather
    than sending them into a 403."""
    client = _user("plain-operator")
    assert client.get("/admin-console/").status_code == 403
    assert client.get("/console/").status_code == 200


def test_the_identity_endpoint_carries_what_the_gate_needs():
    """The console decides from /users/me/, so the fields it reads have
    to be in that payload."""
    client = _user("me-reader", groups=["dpo"])
    body = client.get("/api/v1/security/users/me/").json()
    assert "roles" in body and "is_superuser" in body
    assert "dpo" in body["roles"]
