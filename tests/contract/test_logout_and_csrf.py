"""Signing out, and what a person sees when a token has gone stale.

Django 5 dropped GET logout for a good reason — a prefetching browser or
an <img> tag could sign someone out — but the bare 405 it leaves behind
is what a user meets whenever they bookmark or type /logout/. And the
stock CSRF page explains a "Referer header" to a district officer.
Neither is a 500, so neither shows up in error monitoring; both are
still defects.
"""

import re

import pytest
from django.contrib.auth.models import Group
from django.test import Client


@pytest.fixture
def operator(db, django_user_model):
    u = django_user_model.objects.create_user(username="an-op", password="pw")
    u.groups.add(Group.objects.get(name="enumerator"))
    return u


def _token(html):
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    return m.group(1) if m else None


@pytest.mark.django_db
class TestLogout:

    def test_visiting_logout_directly_is_not_a_405(self, client, operator):
        client.force_login(operator)
        r = client.get("/logout/")
        assert r.status_code == 200, "a bookmarked /logout/ still errors"
        assert b"Sign out?" in r.content

    def test_the_confirmation_carries_a_fresh_token(self, client, operator):
        client.force_login(operator)
        assert _token(client.get("/logout/").content.decode())

    def test_get_does_not_actually_sign_you_out(self, client, operator):
        """A prefetch or an <img> must not end the session."""
        client.force_login(operator)
        client.get("/logout/")
        assert client.get("/").context["user"].is_authenticated

    def test_post_signs_you_out(self, client, operator):
        client.force_login(operator)
        tok = _token(client.get("/logout/").content.decode())
        r = client.post("/logout/", {"csrfmiddlewaretoken": tok})
        assert r.status_code == 302
        assert not client.get("/").context["user"].is_authenticated

    def test_post_signs_you_out_with_csrf_enforced(self, operator):
        c = Client(enforce_csrf_checks=True)
        c.force_login(operator)
        tok = _token(c.get("/logout/").content.decode())
        assert c.post("/logout/", {"csrfmiddlewaretoken": tok}).status_code == 302

    def test_the_masthead_button_still_works(self, operator):
        """The Sign out button posts from the landing page, not /logout/."""
        c = Client(enforce_csrf_checks=True)
        c.force_login(operator)
        tok = _token(c.get("/").content.decode())
        assert tok, "no CSRF token on the landing page"
        assert c.post("/logout/", {"csrfmiddlewaretoken": tok}).status_code == 302

    def test_anonymous_is_sent_home_not_shown_a_sign_out_button(self, client):
        r = client.get("/logout/")
        assert r.status_code == 302 and r["Location"] == "/"


@pytest.mark.django_db
class TestCsrfFailurePage:

    def test_a_stale_post_explains_itself(self, operator):
        c = Client(enforce_csrf_checks=True)
        c.force_login(operator)
        r = c.post("/logout/", {})  # no token: the stale-tab case
        assert r.status_code == 403
        body = r.content.decode()
        assert "open too long" in body
        assert "Referer" not in body, "Django's raw diagnostic reached the user"

    def test_it_offers_a_way_forward(self, operator):
        c = Client(enforce_csrf_checks=True)
        c.force_login(operator)
        body = c.post("/logout/", {}).content.decode()
        assert 'href="/"' in body
