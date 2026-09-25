"""`filterset_fields` without django-filter is a filter that never runs.

DRF ignores `filterset_fields` unless DjangoFilterBackend is installed
and configured. django-filter is not a dependency of this project, so
every such declaration is a no-op that *looks* like a filter: the
endpoint accepts the query parameter, returns 200, and serves
everything.

That is how the household Audit tab came to show the caller's events
across the whole registry while asking for one household's, and the GRM
viewset's own docstring records the same discovery ("declaring
filterset_fields alone was silently a no-op").

So: either django-filter is installed and wired, or no viewset declares
filterset_fields.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from rest_framework import viewsets

import apps


def _django_filter_available() -> bool:
    try:
        importlib.import_module("django_filters")
    except ImportError:
        return False
    from django.conf import settings
    backends = settings.REST_FRAMEWORK.get("DEFAULT_FILTER_BACKENDS", [])
    return any("DjangoFilterBackend" in b for b in backends)


def _viewsets():
    for module_info in pkgutil.walk_packages(apps.__path__, prefix="apps."):
        name = module_info.name
        if not name.endswith((".api", ".views", ".admin_api", ".user_api")):
            continue
        try:
            module = importlib.import_module(name)
        except Exception:  # pragma: no cover — import-time config
            continue
        for _attr, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, viewsets.GenericViewSet)
                and obj.__module__ == name
            ):
                yield name, obj


def test_the_scan_finds_viewsets():
    """Guard the guard — an empty scan would pass silently."""
    assert len(list(_viewsets())) > 10


# Endpoints known to declare a filter that never runs. Every line is an
# endpoint that accepts a query parameter, returns 200, and serves
# unfiltered data. They are listed rather than left failing because
# fixing eleven endpoints was not what this change was for — but the
# list has to shrink, and nothing may join it.
#
# The durable fix is to install django-filter and wire
# DjangoFilterBackend, which makes every declaration below mean what it
# already says. Until then each needs a manual get_queryset, as
# AuditEventViewSet and GrievanceViewSet now have.
KNOWN_SILENT = {
    "apps.data_requests.api.DataRequestViewSet",
    "apps.dqa.api.DqaResultViewSet",
    "apps.dqa.api.DqaRuleViewSet",
    "apps.ingestion_hub.api.ConnectorRunViewSet",
    "apps.ingestion_hub.api.StageRecordViewSet",
    "apps.intake.api.FormVersionViewSet",
    "apps.intake.api.SubmissionViewSet",
    "apps.pmt.api.PMTModelVersionViewSet",
    "apps.pmt.api.PMTResultViewSet",
    "apps.reference_data.api.ChoiceListViewSet",
    "apps.security.api.OperatorScopeViewSet",
    "apps.update_workflow.api.ChangeRequestViewSet",
}


def _declaring_viewsets() -> set[str]:
    return {
        f"{module}.{cls.__name__}"
        for module, cls in _viewsets()
        if getattr(cls, "filterset_fields", None)
    }


@pytest.mark.skipif(
    _django_filter_available(),
    reason="django-filter is installed and wired; filterset_fields works",
)
def test_no_new_endpoint_declares_a_filter_that_cannot_run():
    new = sorted(_declaring_viewsets() - KNOWN_SILENT)
    assert not new, (
        "django-filter is not installed, so these declarations are "
        "ignored and the endpoints silently return unfiltered data. "
        "Filter in get_queryset instead:\n  " + "\n  ".join(new)
    )


@pytest.mark.skipif(
    _django_filter_available(),
    reason="django-filter is installed and wired; filterset_fields works",
)
def test_the_known_list_does_not_rot():
    """A viewset that has been fixed must leave the list.

    Otherwise the list stops describing anything and the next silent
    filter hides inside it.
    """
    stale = sorted(KNOWN_SILENT - _declaring_viewsets())
    assert not stale, (
        "fixed, but still listed as silent: " + ", ".join(stale)
    )


def test_the_audit_endpoint_actually_filters(db, django_user_model):
    """The one this change was for. Asserted against behaviour, not
    against the absence of a declaration."""
    from rest_framework.test import APIClient

    from apps.security.audit import emit

    emit("read", "household", "HH-ONE", actor="someone")
    emit("read", "household", "HH-TWO", actor="someone")
    emit("read", "grievance", "G-ONE", actor="someone")

    user = django_user_model.objects.create_user(
        username="auditor", password="p", is_superuser=True, is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    r = client.get("/api/v1/security/audit-events/", {"entity_id": "HH-ONE"})

    assert r.status_code == 200
    rows = r.data.get("results", r.data)
    assert {row["entity_id"] for row in rows} == {"HH-ONE"}
