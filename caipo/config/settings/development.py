"""Local development. Never use these settings on a reachable host."""

from caipo.config import env

from .base import *

DEBUG = True

SECRET_KEY = env.required("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {"default": env.postgres_database()}

# The development server speaks plain HTTP, over which a browser will not
# return Secure cookies.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
