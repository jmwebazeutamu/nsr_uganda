"""Django settings — NSR MIS Sprint 0 baseline.

Minimal viable configuration. Reads environment via django-environ.
Real configuration lands incrementally as modules go live.

References:
- CLAUDE.md coding standards (UTC at rest, i18n on everything, BigAutoField default)
- ADR-0002 identifier strategy
- ADR-0003 migration policy
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-replace-before-deploy")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    # NSR functional modules
    "apps.intake",
    "apps.data_management",
    "apps.dqa",
    "apps.ddup",
    "apps.identity_verification",
    "apps.update_workflow",
    "apps.pmt",
    "apps.referral",
    "apps.grievance",
    "apps.api_gateway",
    "apps.data_requests",
    "apps.ingestion_hub",
    # NSR cross-cutting modules
    "apps.security",
    "apps.reporting",
    "apps.reference_data",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nsr_mis.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nsr_mis.wsgi.application"
ASGI_APPLICATION = "nsr_mis.asgi.application"

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Sprint 1 baseline: every API call requires an authenticated user
    # via session (browser) or HTTP Basic (test/CLI). Keycloak OIDC is
    # the Sprint 2 swap-in (will register at the front of the list).
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # Lists return {count, next, previous, results}.
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "NSR MIS API",
    "DESCRIPTION": "Uganda National Social Registry MIS — OpenAPI 3.1 contracts.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # DDUP, DQA, PMT, and UPD all declare a "status" field with overlapping
    # choice sets. drf-spectacular collapses identical enums and auto-names
    # the surviving one StatusNNNEnum. Acceptable until we either rename the
    # per-module enum classes or rework consumers off the generated names.
}

# --- Secrets used by apps.security ----------------------------------------
# Dev defaults are always defined so test runs (DEBUG=False) work without
# secrets infra. A system check (apps.security.checks) errors when DEBUG=False
# and these still match the dev defaults, so production cannot boot with
# known-public values.
NSR_NIN_PEPPER = env("NSR_NIN_PEPPER", default="dev-only-nin-pepper-replace-before-deploy")
NSR_DATA_KEY = env("NSR_DATA_KEY", default="6kZf3vUYNDxBcLg3Vh-uYqOjQp4mEX0sIqAJ8u3OZk0=")
