"""Decisions about one article made at the same time, on separate connections (ADR-0022).

These tests commit their data, because other connections must see it, and the
database is emptied after each of them.
"""

import threading
from collections.abc import Callable

import pytest
from django.db import connections

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.articles import services
from caipo.articles.models import ArticleDecision, ArticleLicence
from caipo.core.entry import InvalidEntryError

pytestmark = pytest.mark.django_db(transaction=True)

type ActingAs = Callable[..., AuthenticationContext]

WAIT_SECONDS = 30


def _at_the_same_time(*operations: Callable[[], object]) -> list[object]:
    """Run the operations together, each on its own connection; return results or errors."""
    barrier = threading.Barrier(len(operations))
    results: list[object] = [None] * len(operations)

    def run(index: int, operation: Callable[[], object]) -> None:
        try:
            barrier.wait(timeout=WAIT_SECONDS)
            results[index] = operation()
        except Exception as error:  # recorded and asserted on by the test, not hidden
            results[index] = error
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(index, operation))
        for index, operation in enumerate(operations)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_SECONDS)
        assert not thread.is_alive(), "an operation did not finish"
    return results


def test_two_verdicts_at_once_record_one(acting_as: ActingAs) -> None:
    public_id = services.submit_article(
        actor=acting_as(Role.READER),
        author_name="TEST Author",
        title="TEST article",
        summary="TEST summary",
        body="TEST body",
        licence=ArticleLicence.CC_BY_4_0,
    )
    first = acting_as(Role.REVIEWER, second_factor=True)
    second = acting_as(Role.ADMINISTRATOR, second_factor=True)

    results = _at_the_same_time(
        lambda: services.publish_article(actor=first, article_id=public_id),
        lambda: services.decline_article(actor=second, article_id=public_id, reason="TEST"),
    )

    assert sorted(type(result).__name__ for result in results) == [
        "InvalidEntryError",
        "NoneType",
    ]
    assert all(result is None or isinstance(result, InvalidEntryError) for result in results)
    assert ArticleDecision.objects.count() == 1
