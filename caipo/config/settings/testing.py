"""The test suite. Runs against PostgreSQL, like every other environment (ADR-0002)."""

import secrets

from caipo.config import env

from .base import *

# Generated per process: tests must not depend on a particular key, and no key
# is written down anywhere.
SECRET_KEY = secrets.token_urlsafe(50)
TOTP_ENCRYPTION_KEY = secrets.token_bytes(32)

ALLOWED_HOSTS = ["testserver"]

DATABASES = {"default": env.postgres_database()}

PUBLIC_BASE_URL = "http://testserver"

# Messages are kept in memory, in `django.core.mail.outbox`, and sent nowhere.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
