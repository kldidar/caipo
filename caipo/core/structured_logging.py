"""JSON log formatting (docs/ARCHITECTURE.md §10)."""

import json
import logging
import re
from datetime import UTC, datetime

from django.core.exceptions import PermissionDenied

from caipo.core.correlation import CORRELATION_ATTRIBUTE, get_correlation_id

REDACTED = "[redacted]"

# Attributes every LogRecord carries; anything else was passed through `extra`.
_STANDARD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

_SENSITIVE_FIELD = re.compile(
    r"passw|secret|token|credential|authorization|cookie|session|api_?key|private_?key",
    re.IGNORECASE,
)


def _correlation_id(record: logging.LogRecord) -> str | None:
    """Return the ID of the unit of work a record belongs to.

    A record written after its scope ended, as Django's summary of an error
    response is, still names the object the work was done for under `request`.
    The ID kept on that object is used then. Only the ID is read from it.
    """
    correlation_id = get_correlation_id()
    if correlation_id is None:
        carried = getattr(getattr(record, "request", None), CORRELATION_ATTRIBUTE, None)
        if isinstance(carried, str):
            correlation_id = carried
    return correlation_id


class JsonFormatter(logging.Formatter):
    """Format a log record as one JSON object per line.

    Fields passed through `extra` are included only when their value is a
    plain scalar. That keeps objects such as the request Django attaches to its
    own records, with their headers and cookies, out of the logs. A field whose
    name suggests a credential is replaced with a marker.

    This is a backstop, not a guarantee: it cannot see a secret that a caller
    writes into the message text. Callers must not log secrets, session
    identifiers, document bodies, prompts, or user questions.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int | float | bool | None] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": _correlation_id(record),
        }
        for name, value in vars(record).items():
            if name in _STANDARD_ATTRIBUTES or name in payload:
                continue
            if _SENSITIVE_FIELD.search(name):
                payload[name] = REDACTED
            elif value is None or isinstance(value, str | int | float | bool):
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ExpectedRefusalFilter(logging.Filter):
    """Drop the traceback from Django's summary of a refusal, and keep the line.

    Django logs every response that a PermissionDenied produced at WARNING,
    with the exception attached. A refusal is expected: the code that refused
    has already logged it as a structured event (`access.denied`,
    `authorization.denied`), and the traceback only repeats where the
    exception was raised. The summary line stays, with its status and
    correlation ID. Every other record, the summary of a server error among
    them, keeps its traceback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and isinstance(record.exc_info[1], PermissionDenied):
            record.exc_info = None
            record.exc_text = None
        return True
