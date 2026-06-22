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

from nsr_mis.email_settings import (
    default_email_backend,
    server_email_from_default,
)

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-replace-before-deploy")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# US-076 / DQA-5 — feature flag for the form-based Rule Editor admin
# UI. Defaults: True in dev (where DEBUG=True), False elsewhere so
# the prod rollout has an explicit env switch (DQA_RULE_EDITOR_V2=1).
DQA_RULE_EDITOR_V2 = env.bool("DQA_RULE_EDITOR_V2", default=DEBUG)

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
    "apps.partners",
    # NSR cross-cutting modules
    "apps.security",
    "apps.reporting",
    "apps.reference_data",
    # Admin Console — second front-end behind the same backend
    # (HANDOFF — Admin Console + PMT 2026-05-22).
    "apps.admin_console",
    # Chatbot Assistant — RAG over user manuals (ADR-0021).
    "apps.chatbot",
    # Data Explorer — discovery + aggregate-preview surface (ADR-0023).
    "apps.data_explorer",
    # Consent Management — per-member per-purpose consent (Epic 19,
    # ADR-0024). Gated by CONSENT_MODULE_ENABLED.
    "apps.consent",
]

# US-S23 — gate the partners-module UI surfaces and write endpoints
# behind a flag so the rollout can stage. Read endpoints stay open
# (they're harmless until partner rows exist).
PARTNERS_MODULE_ENABLED = True
# Open-CR evidence file storage (CR-modal slice 3). "file" by default
# (dev convenience), "memory" in tests via conftest, "minio" once the
# production bucket lands. Dir under repo root keeps dev sessions
# self-contained.
UPD_EVIDENCE_STORAGE = env("UPD_EVIDENCE_STORAGE", default="file")
UPD_EVIDENCE_DIR = env(
    "UPD_EVIDENCE_DIR",
    default=str(BASE_DIR / ".upd-evidence"),
)

# US-CHB — gate the chatbot endpoints + Assistant nav entry behind a
# flag. Defaults off — flip after DPIA sign-off (ADR-0021 CHB-O-02).
CHATBOT_ENABLED = env("CHATBOT_ENABLED", default=False)
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
CHATBOT_MODEL = env("CHATBOT_MODEL", default="claude-sonnet-4-6")
# Embedder selector — "sentence" (all-MiniLM-L6-v2 via
# sentence-transformers) for prod, "hash" (deterministic
# dependency-free) for tests + dev without model weights.
CHATBOT_EMBEDDER = env("CHATBOT_EMBEDDER", default="sentence")
# DocuSign client off by default; the in-memory stub provider is the
# default per ADR-0012. CI keeps this false.
PARTNERS_DOCUSIGN_ENABLED = False

# US-S11-044 — gate the intra-household DQA evaluator + the pipeline
# wiring that calls it. Default ON in dev/staging via env, OFF in
# production until the 8 seeded rules pass dual-approval. CI runs
# tests with it ON.
DQA_INTRA_HOUSEHOLD_ENABLED = env(
    "DQA_INTRA_HOUSEHOLD_ENABLED", default=DEBUG,
)

# US-CONSENT (Epic 19, ADR-0024) — gate the Consent Management module:
# all /api/v1/consent/ endpoints, the admin/portal screens, and every
# downstream consent gate (PMT/REF/DRS/DDUP/UPD/DIH/INT). Defaults OFF in
# production until DPO sign-off lands (purpose catalogue, SLA, DPA scopes).
# When off, every consent gate short-circuits to "transparent allow" so
# existing functionality is unchanged. CI runs the consent suite with it ON.
CONSENT_MODULE_ENABLED = env("CONSENT_MODULE_ENABLED", default=DEBUG)
# Withdrawal SLA in days (CONSENT-O-03; DPPA §29 + Regs 2021). 30 days.
CONSENT_WITHDRAWAL_SLA_DAYS = env.int("CONSENT_WITHDRAWAL_SLA_DAYS", default=30)
# MinIO object-store prefix for consent evidence (signatures / thumbprints /
# witness statements / DPA documents). The asset bytes live in MinIO; the
# object key is recorded on ConsentEvidence.
CONSENT_EVIDENCE_STORAGE = env("CONSENT_EVIDENCE_STORAGE", default="file")
CONSENT_EVIDENCE_DIR = env(
    "CONSENT_EVIDENCE_DIR", default=str(BASE_DIR / ".consent-evidence"),
)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # US-S11-042 — must sit after AuthenticationMiddleware so
    # request.user is populated, but before any view dispatch so
    # the read-only guard can short-circuit non-SAFE writes.
    "apps.security.impersonation.ImpersonationGuardMiddleware",
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
    # US-DATA-EXP-001 — analytics replica routed by
    # apps.data_explorer.db_router.AnalyticsReplicaRouter. In dev/test
    # the alias points at the same database as `default` so the router
    # is a no-op; staging/prod override DATABASE_URL_ANALYTICS to point
    # at the actual Postgres read replica (per ADR-0023 D2).
    "analytics_replica": env.db_url(
        "DATABASE_URL_ANALYTICS",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

# In tests, point `analytics_replica` at the same TEST database Django
# created for `default`. Without this pytest-django spins up a second
# empty test DB for the replica alias and DATA-EXP reads can't see
# any seeded rows (NoSuchTable on data_requests_*, etc.).
DATABASES["analytics_replica"]["TEST"] = {"MIRROR": "default"}

# US-DATA-EXP-001 — router gates DATA-EXP reads to analytics_replica
# and forbids writes against the matview-backed unmanaged models.
DATABASE_ROUTERS = ["apps.data_explorer.db_router.AnalyticsReplicaRouter"]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# collectstatic target. In the production image the web entrypoint runs
# collectstatic into this dir on a shared volume; Caddy serves /static/*
# from it. Overridable via env for non-container deploys.
STATIC_ROOT = env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))

# Media (UPD evidence, consent evidence, DRS bundles default to file
# storage). NOT publicly served — these are sensitive and reached only
# through authenticated Django views; the dir lives on a persistent
# volume in prod.
MEDIA_URL = "media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Production TLS hardening ----------------------------------------------
# Opt-in via NSR_SECURE_SSL so the test suite (which runs DEBUG=False but
# over plain HTTP) is unaffected — only the prod .env sets it True. The
# TLS-terminating reverse proxy (Caddy) forwards X-Forwarded-Proto and
# performs the http->https redirect itself, so Django trusts the header
# rather than issuing its own redirect.
if env.bool("NSR_SECURE_SSL", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

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
# 'file'   = disk-backed (default for dev). Bundles persist across
#            `runserver` restarts, which the in-process dict never did
#            (BUG-S27-032 — partner downloads kept 404ing after a restart).
# 'memory' = in-process dict (test-suite default; see conftest.py).
# 'minio'  = MinIO client (placeholder, raises NotImplementedError until
#            DRS-O-02 closes — see apps.data_requests.storage).
DRS_BUNDLE_STORAGE = env("DRS_BUNDLE_STORAGE", default="file")
DRS_BUNDLE_DIR = env(
    "DRS_BUNDLE_DIR",
    default=str(BASE_DIR / ".drs-bundles"),
)

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

# --- Chain-break alert channels (US-S18-004) ------------------------------
# Both default to empty so dev/CI never fires; set via environment to
# enable production alerting. The Celery audit-chain task
# (apps.security.tasks.verify_audit_chain_task) reads these on each
# beat — no service restart needed to roll out / pause alerting.
#
# SLACK_WEBHOOK_URL accepts any Slack incoming-webhook HTTPS URL.
# DPO_EMAIL goes through Django's email backend (configure
# EMAIL_BACKEND + SMTP creds for real delivery; defaults to
# console output in dev).
SLACK_WEBHOOK_URL = env("SLACK_WEBHOOK_URL", default="")
DPO_EMAIL = env("DPO_EMAIL", default="")

# --- Email / SMTP ---------------------------------------------------------
# If SMTP credentials are present, default to the SMTP backend. That
# keeps deployed environments working even if EMAIL_BACKEND was omitted
# from the secrets bundle. Otherwise fall back to the console backend so
# local dev and CI stay side-effect free unless explicitly configured.
#
# Default host points at the quasar.ug SMTP relay — same one the
# `comms` rental_project uses. Credentials are NEVER hardcoded; they
# come from the environment so we don't ship secrets in git.
_email_host_user = env("EMAIL_HOST_USER", default="")
_email_host_password = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default=default_email_backend(
        host_user=_email_host_user,
        host_password=_email_host_password,
    ),
)
EMAIL_HOST = env("EMAIL_HOST", default="comms.quasar.ug")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = _email_host_user
EMAIL_HOST_PASSWORD = _email_host_password
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=30)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="NSR MIS <admin@quasar.ug>",
)
SERVER_EMAIL = env(
    "SERVER_EMAIL",
    default=server_email_from_default(DEFAULT_FROM_EMAIL),
)

# US-117b — feature flag for the Questionnaire builder admin UI
# (section/question tree, up-down reorder, inline expression
# validation). Defaults to True in dev (DEBUG=True), False in prod
# so the rollout has an explicit env switch. Mirrors the DQA Rule
# Editor flag (US-076).
QUESTIONNAIRE_EDITOR_V2 = env.bool("QUESTIONNAIRE_EDITOR_V2", default=DEBUG)

# US-DATA-EXP-001 — feature flag for the Data Explorer (DATA-EXP) module
# (catalogue + k-anonymity-enforced aggregate API). Per ADR-0023 D9 the
# default is False; dev/staging set it True. When the flag is False
# every DATA-EXP endpoint returns 503 and the sidebar link is hidden.
DATA_EXPLORER_ENABLED = env.bool("DATA_EXPLORER_ENABLED", default=DEBUG)
