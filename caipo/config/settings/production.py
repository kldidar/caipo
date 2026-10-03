"""Production baseline. Not a complete production configuration.

Everything that depends on how the application is deployed is still missing:
TLS redirection, HSTS, the trusted proxy header, trusted CSRF origins, the
Content Security Policy, per-component database roles, and how the keys below
are stored, supplied, and rotated, and the email delivery service, without
which no message is sent and no account can be invited (ADR-0015). Those
follow the deployment decision (ADR-0008, Proposed) and must not be guessed
here.
"""

from caipo.config import env

from .base import *

SECRET_KEY = env.secret_key("DJANGO_SECRET_KEY")
TOTP_ENCRYPTION_KEY = env.encryption_key("TOTP_ENCRYPTION_KEY")

ALLOWED_HOSTS = env.host_list("DJANGO_ALLOWED_HOSTS")

DATABASES = {"default": env.postgres_database()}

PUBLIC_BASE_URL = env.https_origin("CAIPO_PUBLIC_URL")
