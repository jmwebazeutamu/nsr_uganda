"""Self-service profile and shell affordance contract tests."""

import pytest
from django.contrib.auth.models import Group


@pytest.fixture
def operator(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="profile-operator",
        password="pw",
        first_name="Before",
        email="before@example.test",
    )
    user.groups.add(Group.objects.get(name="enumerator"))
    return user


@pytest.fixture
def administrator(db, django_user_model):
    user = django_user_model.objects.create_user(username="profile-admin", password="pw")
    user.groups.add(Group.objects.get(name="nsr_admin"))
    return user


@pytest.mark.django_db
class TestProfile:
    def test_profile_requires_a_session(self, client):
        response = client.get("/profile/")
        assert response.status_code == 302
        assert response["Location"].startswith("/login/")

    def test_profile_shows_identity_and_assigned_roles(self, client, operator):
        client.force_login(operator)
        response = client.get("/profile/")
        assert response.status_code == 200
        assert b"profile-operator" in response.content
        assert b"enumerator" in response.content

    def test_profile_updates_only_the_signed_in_users_contact_details(self, client, operator):
        client.force_login(operator)
        response = client.post("/profile/", {
            "first_name": "Updated",
            "last_name": "Operator",
            "email": "updated@example.test",
        })
        assert response.status_code == 302
        assert response["Location"] == "/profile/?updated=1"

        operator.refresh_from_db()
        assert operator.first_name == "Updated"
        assert operator.last_name == "Operator"
        assert operator.email == "updated@example.test"
        assert operator.username == "profile-operator"

    def test_operator_console_has_profile_and_sign_out_controls(self, client, operator):
        client.force_login(operator)
        response = client.get("/console/app.jsx")
        assert response.status_code == 200
        body = b"".join(response.streaming_content)
        assert b"AccountMenu" in body
        menu_response = client.get("/console/components.jsx")
        menu_body = b"".join(menu_response.streaming_content)
        assert menu_response.status_code == 200
        assert b"View/Edit Profile" in menu_body
        assert b"Change Password" in menu_body
        assert b"Logout" in menu_body
        assert b"nsrSignOut" in menu_body

    def test_admin_console_has_profile_and_sign_out_controls(self, client, administrator):
        client.force_login(administrator)
        response = client.get("/admin-console/v0.1/screens/app-admin.jsx")
        assert response.status_code == 200
        body = b"".join(response.streaming_content)
        assert b"AccountMenu" in body

    def test_operator_can_change_their_own_password(self, client, operator):
        client.force_login(operator)
        response = client.post("/profile/password/", {
            "old_password": "pw",
            "new_password1": "a-longer-safe-password-123",
            "new_password2": "a-longer-safe-password-123",
        })
        assert response.status_code == 302
        assert response["Location"] == "/profile/?password_updated=1"

        operator.refresh_from_db()
        assert operator.check_password("a-longer-safe-password-123")


class TestMastheadReturnsHome:
    """The masthead is the way back to the welcome screen.

    It is a real anchor rather than an onClick handler so it is keyboard
    reachable and behaves like a link (status bar, middle-click,
    open-in-new-tab). Both shells carry it.
    """

    SHELLS = [
        "design/app.jsx",
        "design/v0.1/screens/app-admin.jsx",
    ]

    def test_both_shells_link_the_masthead_to_the_welcome_screen(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent.parent
        for shell in self.SHELLS:
            src = (repo / shell).read_text()
            assert '<a className="topbar-brand" href="/home/"' in src, (
                f"{shell}: the masthead no longer links to /home/, so there "
                f"is no way back to the welcome screen from the console."
            )

    def test_welcome_screen_is_reachable_for_a_signed_in_operator(
        self, client, operator,
    ):
        client.force_login(operator)
        response = client.get("/home/")
        assert response.status_code == 200, (
            "/home/ is what the masthead points at; if it does not answer, "
            "the masthead is a dead link."
        )
