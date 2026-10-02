"""ASGI entrypoint."""

import os

from django.core.asgi import get_asgi_application

# Production is the default so that a missing variable can never select debug settings.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "caipo.config.settings.production")

application = get_asgi_application()
