"""Production baseline. Not a complete production configuration.

Everything that depends on how the application is deployed is still missing:
TLS redirection, HSTS, the trusted proxy header, trusted CSRF origins, the
Content Security Policy, and per-component database roles. Those follow the
deployment decision (ADR-0008, Proposed) and must not be guessed here.
"""

from caipo.config import env

from .base import *

SECRET_KEY = env.secret_key("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.host_list("DJANGO_ALLOWED_HOSTS")

DATABASES = {"default": env.postgres_database()}
