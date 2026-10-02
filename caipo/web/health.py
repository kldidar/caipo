"""Liveness and readiness endpoints for process supervisors and load balancers.

Liveness says the process can serve a request and touches nothing else, so a
database outage does not get a healthy process restarted. Readiness says the
process can do useful work, which needs the database.
"""

import logging

from django.db import Error, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from caipo.web.access import public

logger = logging.getLogger(__name__)

OK = "ok"
UNAVAILABLE = "unavailable"


def _database_is_reachable() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Error as error:
        # Only the error class is recorded: driver messages can carry
        # connection details, and nothing of the error reaches the response.
        logger.error(
            "Readiness check failed",
            extra={"event": "health.readiness_failed", "error_type": type(error).__name__},
        )
        return False
    return True


@public
@never_cache
@require_GET
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": OK})


@public
@never_cache
@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    database = OK if _database_is_reachable() else UNAVAILABLE
    return JsonResponse(
        {"status": database, "checks": {"database": database}},
        status=200 if database == OK else 503,
    )
