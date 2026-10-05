"""Settings shared by every environment.

This module reads nothing from the environment, so it imports anywhere,
including under the type checker. Each environment module adds the values that
come from the environment: SECRET_KEY, TOTP_ENCRYPTION_KEY, DATABASES,
ALLOWED_HOSTS, and PUBLIC_BASE_URL.

Defaults here are the restrictive ones. An environment module loosens a value
only where it must, and says why.
"""

from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

DEBUG = False

ALLOWED_HOSTS: list[str] = []

# django.contrib.admin is deliberately absent. ADR-0007 puts it on a
# non-default path behind TOTP. It is a later increment of its own.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "caipo.accounts",
    "caipo.web",
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

LOGIN_URL = "login"

# Sign-in throttling. A failed sign-in counts against the email address it
# named and against the address it came from. Once either count is reached
# within the window, further attempts are refused until earlier failures have
# aged out of it; nothing is locked permanently. Repository-versioned on
# purpose: these are not read from the environment.
LOGIN_THROTTLE_WINDOW = timedelta(minutes=15)
LOGIN_THROTTLE_ACCOUNT_FAILURES = 5
LOGIN_THROTTLE_SOURCE_FAILURES = 20

# Second factor (ADR-0014). Repository-versioned like the limits above, and
# for the same reason. None of these can turn the requirement off: which roles
# need a second factor is part of the authorization policy, not a setting.

# The name an authenticator application shows beside the account.
TOTP_ISSUER = "CAIPO"
# A code is accepted for the current 30-second step and this many steps on
# either side, to allow for a clock that is slightly off.
TOTP_DRIFT_STEPS = 1
# The key that encrypts TOTP secrets, as 32 bytes. It has no value here: each
# environment module must supply it, and code that needs it fails without it.
TOTP_ENCRYPTION_KEY: bytes

# An enrolment that needs no approval and is not confirmed with a code within
# this time is void.
MFA_ENROLLMENT_LIFETIME = timedelta(minutes=10)
# An enrolment that needs an Administrator's approval waits this long for the
# decision and, once approved, as long again for its first code. It waits for
# people, so it is counted in days.
MFA_APPROVAL_LIFETIME = timedelta(hours=72)
# After the password is accepted, the code must follow within this time.
MFA_CHALLENGE_LIFETIME = timedelta(minutes=5)
# Wrong codes for one account, in any of sign-in, enrolment, and disabling,
# before further codes are refused unexamined until earlier ones age out.
MFA_THROTTLE_WINDOW = timedelta(minutes=15)
MFA_THROTTLE_FAILURES = 5

# Account activation (ADR-0015). Repository-versioned like the limits above.

# The message that lets a new account verify its email address and choose its
# password stops working after this time. An Administrator can send another.
ACCOUNT_ACTIVATION_LIFETIME = timedelta(hours=48)
# Refused activation attempts from one source before further attempts are
# refused unexamined until earlier ones age out.
ACCOUNT_ACTIVATION_THROTTLE_WINDOW = timedelta(minutes=15)
ACCOUNT_ACTIVATION_THROTTLE_FAILURES = 10

# Password reset (ADR-0016). Repository-versioned like the limits above. The
# names avoid Django's own PASSWORD_RESET_TIMEOUT, which belongs to a token
# generator this project does not use.

# The message that lets the owner of an active account choose a new password
# stops working after this time.
PASSWORD_RESET_LIFETIME = timedelta(hours=1)
# Reset requests for one email address, whether or not it has an account,
# before further requests for it issue no token and send no message.
PASSWORD_RESET_REQUEST_EMAIL_WINDOW = timedelta(hours=1)
PASSWORD_RESET_REQUEST_EMAIL_LIMIT = 5
# The same, for requests from one source.
PASSWORD_RESET_REQUEST_SOURCE_WINDOW = timedelta(minutes=15)
PASSWORD_RESET_REQUEST_SOURCE_LIMIT = 20
# Refused reset tokens from one source before further submissions are refused
# unexamined until earlier ones age out.
PASSWORD_RESET_THROTTLE_WINDOW = timedelta(minutes=15)
PASSWORD_RESET_THROTTLE_FAILURES = 10

# Recovery of a lost second factor (ADR-0017). Repository-versioned like the
# limits above.

# A recovery request that no Administrator has authorised within this time is
# void. The person reaches an Administrator first and asks second.
MFA_RECOVERY_REQUEST_LIFETIME = timedelta(minutes=30)
# No recovery is finalised within this time of the account's latest
# successful password reset.
MFA_RECOVERY_COOLING_OFF = timedelta(hours=24)
# Recovery requests for one account before further requests for it are
# refused until earlier ones age out.
MFA_RECOVERY_REQUEST_ACCOUNT_WINDOW = timedelta(hours=1)
MFA_RECOVERY_REQUEST_ACCOUNT_LIMIT = 5
# The same, for requests from one source.
MFA_RECOVERY_REQUEST_SOURCE_WINDOW = timedelta(minutes=15)
MFA_RECOVERY_REQUEST_SOURCE_LIMIT = 20
# Refused recovery submissions from one source before further submissions are
# refused unexamined until earlier ones age out.
MFA_RECOVERY_THROTTLE_WINDOW = timedelta(minutes=15)
MFA_RECOVERY_THROTTLE_FAILURES = 10

# The address of this site as its users reach it, scheme and host with no
# path, for links in messages. It has no value here: each environment module
# must supply it. It is never taken from a request, whose Host header a
# client chooses.
PUBLIC_BASE_URL: str

# Email (ADR-0015). No delivery service is chosen: that belongs to deployment
# (ADR-0008). Until an environment names a backend, every message is refused,
# so nothing is sent by accident.
EMAIL_BACKEND = "caipo.core.mail.RefusingEmailBackend"
# A placeholder under a reserved name that can never receive mail (RFC 2606).
# The real sender is set with the delivery service.
DEFAULT_FROM_EMAIL = "CAIPO <no-reply@caipo.invalid>"

# Sessions are held on the server; the cookie carries only an identifier. A
# session ends when the browser closes and, whatever the browser does, twelve
# hours after sign-in.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = False

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
