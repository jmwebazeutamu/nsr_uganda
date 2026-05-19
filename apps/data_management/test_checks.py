"""Tests for the data_management.E001 system check.

The clean tree passes; introducing a `choices=` argument on any
field registered in choice_field_map should flag the offender.
"""

from __future__ import annotations

from django.core.checks import Error
from django.db import models

from apps.data_management.checks import (
    _iter_field_violations,
    check_no_textchoices_on_mapped_fields,
)


def test_clean_tree_has_no_violations():
    errors = list(check_no_textchoices_on_mapped_fields(app_configs=None))
    assert errors == []


def test_check_emits_error_when_field_has_choices(monkeypatch):
    """Synthesize a model with choices= on a mapped field and assert
    the check flags it. We monkeypatch _registered_field_maps so the
    test doesn't have to mutate apps.data_management.models."""
    from apps.data_management import checks as checks_mod

    class _FakeChoices(models.TextChoices):
        A = "a", "A"

    class _FakeModel(models.Model):
        coded_field = models.CharField(
            max_length=32, choices=_FakeChoices.choices,
        )

        class Meta:
            app_label = "data_management"
            abstract = True

    # Construct a non-abstract clone so Django can introspect the field.
    non_abstract = type(
        "FakeModel",
        (_FakeModel,),
        {"__module__": "apps.data_management.tests"},
    )
    non_abstract._meta.abstract = False

    fmap = {"coded_field": ("partner_type", "single")}

    def _fake_maps():
        return [("data_management", non_abstract._meta.model_name, fmap)]

    monkeypatch.setattr(checks_mod, "_registered_field_maps", _fake_maps)

    # _iter_field_violations resolves models via django_apps.get_model;
    # the fake model isn't registered, so it returns LookupError and
    # skips silently. To prove the choices=-flagging branch, we patch
    # get_model to hand back our fake.
    from django.apps import apps as django_apps

    def _fake_get_model(app_label, model_name):
        return non_abstract
    monkeypatch.setattr(django_apps, "get_model", _fake_get_model)

    errors = list(_iter_field_violations())
    assert any(isinstance(e, Error) and e.id == "data_management.E001"
               for e in errors)
    assert any("choices=" in (e.msg or "") for e in errors)


def test_check_emits_error_for_unknown_field(monkeypatch):
    """If choice_field_map references a field that doesn't exist on
    the model, the check flags it loudly — surfaces typos."""
    from apps.data_management import checks as checks_mod

    fmap = {"nonexistent_field": ("tenure", "single")}

    def _fake_maps():
        return [("data_management", "Household", fmap)]
    monkeypatch.setattr(checks_mod, "_registered_field_maps", _fake_maps)

    errors = list(_iter_field_violations())
    msgs = [e.msg for e in errors]
    assert any("unknown field" in m for m in msgs)
