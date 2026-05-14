from django.conf import settings
from django.urls import path

from .api import NiraMockVerifyView

urlpatterns = []

# The mock is dev/test-only. Fence the URL registration itself so a
# DEBUG flip in production cannot accidentally expose a NIN-to-record
# oracle (the view also 404s on settings.DEBUG=False, defence in depth).
if settings.DEBUG:
    urlpatterns += [
        path("nira-mock/verify", NiraMockVerifyView.as_view(), name="nira-mock-verify"),
    ]
