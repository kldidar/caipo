import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

from caipo.core.correlation import correlation_scope
from caipo.core.structured_logging import REDACTED, JsonFormatter

TEST_CREDENTIAL = "TEST-credential-value"


def _format(
    message: str = "TEST message",
    args: tuple[object, ...] = (),
    extra: dict[str, object] | None = None,
    exc_info: Any = None,
) -> dict[str, Any]:
    record = logging.getLogger("caipo.test").makeRecord(
        "caipo.test", logging.WARNING, __file__, 0, message, args, exc_info, extra=extra
    )
    line = JsonFormatter().format(record)
    assert "\n" not in line
    parsed: dict[str, Any] = json.loads(line)
    return parsed


def test_record_has_timestamp_level_logger_and_message() -> None:
    entry = _format("TEST %s", ("message",))

    assert entry["level"] == "WARNING"
    assert entry["logger"] == "caipo.test"
    assert entry["message"] == "TEST message"
    assert datetime.fromisoformat(entry["timestamp"]).utcoffset() == timedelta(0)


def test_record_carries_the_correlation_id() -> None:
    assert _format()["correlation_id"] is None

    with correlation_scope() as correlation_id:
        assert _format()["correlation_id"] == correlation_id


def test_scalar_extra_fields_are_included() -> None:
    entry = _format(extra={"event": "TEST.event", "count": 3, "flag": True, "missing": None})

    assert entry["event"] == "TEST.event"
    assert entry["count"] == 3
    assert entry["flag"] is True
    assert entry["missing"] is None


def test_fields_named_like_credentials_are_redacted() -> None:
    names = ["password", "new_passwd", "api_key", "apikey", "auth_token", "client_secret"]
    names += ["Authorization", "cookie", "sessionid", "credentials", "private_key"]

    entry = _format(extra=dict.fromkeys(names, TEST_CREDENTIAL))

    assert {entry[name] for name in names} == {REDACTED}
    assert TEST_CREDENTIAL not in json.dumps(entry)


def test_non_scalar_extra_fields_are_dropped() -> None:
    class Carrier:
        def __repr__(self) -> str:
            return TEST_CREDENTIAL

    entry = _format(extra={"request": Carrier(), "headers": {"Cookie": TEST_CREDENTIAL}})

    assert "request" not in entry
    assert "headers" not in entry
    assert TEST_CREDENTIAL not in json.dumps(entry)


def test_extra_fields_cannot_replace_the_core_fields() -> None:
    entry = _format(extra={"level": "TEST-forged", "logger": "TEST-forged"})

    assert entry["level"] == "WARNING"
    assert entry["logger"] == "caipo.test"


def test_exception_is_included() -> None:
    try:
        raise ValueError("TEST failure")
    except ValueError:
        entry = _format(exc_info=sys.exc_info())

    assert "ValueError: TEST failure" in entry["exception"]


def test_non_ascii_text_is_kept_readable() -> None:
    line = JsonFormatter().format(
        logging.makeLogRecord({"name": "caipo.test", "msg": "TEST сообщение ýazgy"})
    )

    assert "TEST сообщение ýazgy" in line
