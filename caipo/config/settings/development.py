"""Local development. Never use these settings on a reachable host."""

from caipo.config import env

from .base import *
from .base import BASE_DIR

DEBUG = True

SECRET_KEY = env.required("DJANGO_SECRET_KEY")
TOTP_ENCRYPTION_KEY = env.encryption_key("TOTP_ENCRYPTION_KEY")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {"default": env.postgres_database()}

PUBLIC_BASE_URL = "http://127.0.0.1:8000"

# Messages are written to files in a directory that git ignores and are sent
# nowhere. Not printed to the terminal: an activation message holds a link
# that must not appear among the logs.
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = BASE_DIR / "data" / "outbox"

# The development server speaks plain HTTP, over which a browser will not
# return Secure cookies.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
