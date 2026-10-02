"""Settings shared by every environment.

This module reads nothing from the environment, so it imports anywhere,
including under the type checker. Each environment module adds the values that
come from the environment: SECRET_KEY, DATABASES, and ALLOWED_HOSTS.

Defaults here are the restrictive ones. An environment module loosens a value
only where it must, and says why.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

DEBUG = False

ALLOWED_HOSTS: list[str] = []

# django.contrib.admin is deliberately absent. ADR-0007 puts it on a
# non-default path behind TOTP, and TOTP does not exist yet.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "caipo.accounts",
]

MIDDLEWARE = [
    "caipo.web.middleware.CorrelationIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "caipo.web.middleware.AccessDeclarationMiddleware",
]

ROOT_URLCONF = "caipo.config.urls"
WSGI_APPLICATION = "caipo.config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication (ADR-0007)

AUTH_USER_MODEL = "accounts.User"

# Argon2 only: there are no older hashes to stay compatible with.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Cookies are sent over TLS only, unless an environment says otherwise.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Time and language (ADR-0010: English at launch, internationalisation enabled)

TIME_ZONE = "UTC"
USE_TZ = True

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English")]
USE_I18N = True

# Files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Placeholder only. No URL serves this directory, and artifacts never live in
# it: they belong to the content-addressed artifact store (SECURITY.md).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Logging: structured JSON on standard output (docs/ARCHITECTURE.md §10)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "caipo.core.structured_logging.JsonFormatter"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {
        # Named so that Django's own default handlers are replaced and these
        # loggers reach the root handler once, in the same format as the rest.
        "django": {"level": "INFO", "propagate": True},
        "django.server": {"level": "INFO", "propagate": True},
    },
}
