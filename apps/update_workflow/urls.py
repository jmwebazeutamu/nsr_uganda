from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import ChangeRequestViewSet, CurrentValuesView, FieldCatalogView

router = DefaultRouter()
router.register(r"change-requests", ChangeRequestViewSet, basename="change-request")

urlpatterns = [
    *router.urls,
    # US-S28-CATALOG — the Open-CR modal reads its field catalog +
    # resolved ChoiceList options from this single round-trip.
    path("field-catalog/", FieldCatalogView.as_view(), name="upd-field-catalog"),
    path("current-values/", CurrentValuesView.as_view(), name="upd-current-values"),
]
