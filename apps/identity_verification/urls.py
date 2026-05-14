from django.urls import path

from .api import NiraMockVerifyView

urlpatterns = [
    path("nira-mock/verify", NiraMockVerifyView.as_view(), name="nira-mock-verify"),
]
