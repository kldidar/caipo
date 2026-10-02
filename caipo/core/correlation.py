"""Correlation IDs: one identifier that ties together the log lines of a unit of work.

Holds no HTTP knowledge. The web package opens a scope per request.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


# Name under which the owner of a unit of work may also keep its ID on an
# object of its own, for log records written after the scope has ended.
CORRELATION_ATTRIBUTE = "correlation_id"


def get_correlation_id() -> str | None:
    """Return the correlation ID of the current unit of work, or None outside one."""
    return _correlation_id.get()


@contextmanager
def correlation_scope() -> Iterator[str]:
    """Run the enclosed block under a newly generated correlation ID.

    The ID is always generated here and never taken from a caller, so untrusted
    input cannot choose what appears in the logs. The previous value is
    restored on exit, including when the block raises.
    """
    correlation_id = uuid.uuid4().hex
    token = _correlation_id.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id.reset(token)
