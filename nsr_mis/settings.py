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
    # Lists return {count, next, previous, results}. DefaultPagination
    # honours `?page_size=` up to MAX_PAGE_SIZE (500) per ADR-0008.
    # Before ADR-0008 the React side was passing page_size=4/100/200
    # and getting 50 back (DRF default ignores the param) — fixed
    # by switching to the project-owned subclass.
    "DEFAULT_PAGINATION_CLASS": "apps.security.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    # Throttling — only the rate scopes are declared globally; each
    # throttled view names its scope via UserRateThrottle.scope. The
    # bulk extract download (S8-003) is the first throttled action;
    # add more scopes here as they're needed. Rates are
    # environment-tunable so ops can adjust without a deploy.
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "1000/min",
        "drs-download": env("DRS_DOWNLOAD_THROTTLE_RATE", default="10/min"),
    },
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

# --- IDV / NIRA client selection ------------------------------------------
# Switches between the in-process mock and the live NIRA HTTP client.
# Live client raises NotImplementedError until the sandbox creds are
# provisioned (NIRA-O-01). See apps.identity_verification.client.
NIRA_PROVIDER = env("NIRA_PROVIDER", default="mock")

# --- DRS bundle storage backend -------------------------------------------
# 'memory' = in-process dict (dev / CI default).
# 'minio'  = MinIO client (placeholder, raises NotImplementedError until
#            DRS-O-02 closes — see apps.data_requests.storage).
DRS_BUNDLE_STORAGE = env("DRS_BUNDLE_STORAGE", default="memory")

# --- Celery -------------------------------------------------------------
# Beat schedule lives in nsr_mis/celery.py. CELERY_ENABLED is a soft
# flag — when False, the worker / beat processes simply aren't started
# in production. Task code is always importable so unit tests can call
# .run() / .apply() without a broker.
CELERY_ENABLED = env("CELERY_ENABLED", default=False)
CELERY_BROKER_URL = env("CELERY_BROKER_URL",
                         default="memory://")  # in-memory broker for dev/CI
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="cache+memory://")
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER", default=True)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "Africa/Kampala"
CELERY_TASK_SERIALIZER = "json"
