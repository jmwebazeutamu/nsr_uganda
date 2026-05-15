from django.urls import path

from .api import NiraMockVerifyView

# The mock is gated at the view level — NiraMockVerifyView.post() raises
# Http404 when settings.DEBUG is False. The previous URL-level fence was
# order-sensitive (urls.py imports at module-load time with DEBUG=False
# default, which broke pytest-django suites that flip DEBUG per-test).
# Defense remains: the URL exists, but the view refuses to serve outside
# DEBUG, and US-S1-003 system-check security.E001-E004 prevents booting
# production with DEBUG=False + dev secrets.
urlpatterns = [
    path("nira-mock/verify", NiraMockVerifyView.as_view(), name="nira-mock-verify"),
]
