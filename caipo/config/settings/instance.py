"""The public demonstration instance (ADR-0024): production settings, hardened for one host.

It runs on Render's free web service behind Render's proxy, which ends TLS,
with a PostgreSQL database on Neon that requires TLS. It holds demonstration
and reference data only. Registration and password reset are closed, because
the instance sends no message, and the demonstration Reader's address and
password are shown on the sign-in page. Everything here follows ADR-0024
points 5 to 8; `manage.py check --deploy` passes with these settings.
"""

from caipo.config import env

from .production import *
from .production import DATABASES, MIDDLEWARE, PUBLIC_BASE_URL

DEMONSTRATION_INSTANCE = True

# TLS ends at Render's proxy, which says so in X-Forwarded-Proto. The
# application listens only behind it, so no client can reach it directly to
# write that header itself. Health checks come from Render's own network
# without it, so they are not redirected.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
CSRF_TRUSTED_ORIGINS = [PUBLIC_BASE_URL]

# Neon accepts only encrypted connections. New objects, not changes to the
# ones imported: the modules this one builds on stay as they are.
DATABASES = {
    "default": {
        **DATABASES["default"],
        "OPTIONS": {**DATABASES["default"]["OPTIONS"], "sslmode": "require"},
    }
}

# Static files are served by the web process, compressed, under names that
# carry their hash, so they can be cached for a year.
_SECURITY = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1
MIDDLEWARE = [
    *MIDDLEWARE[:_SECURITY],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[_SECURITY:],
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

REGISTRATION_OPEN = False
PASSWORD_RESET_OPEN = False

# The demonstration Reader of seed_demo is shared: its password is chosen by
# the owner, entered in Render's settings, and shown on the sign-in page.
SHARED_ACCOUNT_EMAIL = "demo.reader@caipo.test"
SHARED_ACCOUNT_PASSWORD = env.required("CAIPO_SHARED_PASSWORD")

# Render serves onrender.com through Cloudflare, which writes CF-Connecting-IP
# itself and refuses a request that already carries one (ADR-0026). X-Forwarded-For is not
# read: Render keeps what the client wrote there, and on Day 47 no count of
# entries from the right gave the client's address. Measured with forged
# headers before the link is given out (docs/INSTANCE.md).
CLIENT_ADDRESS_HEADER = "HTTP_CF_CONNECTING_IP"
