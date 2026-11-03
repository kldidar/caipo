"""The services and selectors of contributed articles (ADR-0022)."""

import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from django.conf import LazySettings
from django.core.exceptions import PermissionDenied

from caipo.accounts.models import AuditEvent
from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.accounts.tests.fixtures import Clock
from caipo.articles import selectors, services
from caipo.articles.models import Article, ArticleDecision, ArticleLicence, ArticleStatus
from caipo.core.entry import InvalidEntryError, RecordNotFoundError

pytestmark = pytest.mark.django_db

type ActingAs = Callable[..., AuthenticationContext]

# Visibly synthetic.
LICENCE = ArticleLicence.CC_BY_4_0
REASON = "TEST reason: outside the scope of CAIPO."


@pytest.fixture
def reader(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.READER)


@pytest.fixture
def other_reader(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.READER)


@pytest.fixture
def reviewer(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.REVIEWER, second_factor=True)


@pytest.fixture
def administrator(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.ADMINISTRATOR, second_factor=True)


def _submit(actor: AuthenticationContext, title: str = "TEST article", **changes: str) -> uuid.UUID:
    fields = {
        "author_name": "TEST Author",
        "title": title,
        "summary": "TEST summary of a synthetic article.",
        "body": "TEST first paragraph.\n\nTEST second paragraph.",
        "licence": LICENCE,
        **changes,
    }
    return services.submit_article(actor=actor, **fields)


def _audit() -> list[tuple[str, str, uuid.UUID]]:
    return list(
        AuditEvent.objects.filter(target_type__startswith="articles.")
        .order_by("id")
        .values_list("action", "target_type", "target_public_id")
    )


# --- Sending an article --------------------------------------------------------------------


def test_an_article_is_stored_as_sent_and_awaits_review(reader: AuthenticationContext) -> None:
    public_id = _submit(reader)

    article = Article.objects.get(public_id=public_id)
    assert article.author == reader.user
    assert (article.author_name, article.title, article.licence) == (
        "TEST Author",
        "TEST article",
        LICENCE,
    )
    assert article.body == "TEST first paragraph.\n\nTEST second paragraph."
    assert not ArticleDecision.objects.exists()
    assert _audit() == [("created", "articles.article", public_id)]
    entry = selectors.article(reader, public_id)
    assert entry is not None and entry.status == ArticleStatus.AWAITING_REVIEW


def test_every_role_that_reads_the_workspace_can_send_one(acting_as: ActingAs) -> None:
    for role in (Role.READER, Role.RESEARCHER):
        _submit(acting_as(role))
    _submit(acting_as(Role.REVIEWER, second_factor=True))

    assert Article.objects.count() == 3


def test_an_administrator_alone_cannot_send_one(administrator: AuthenticationContext) -> None:
    with pytest.raises(PermissionDenied):
        _submit(administrator)

    assert not Article.objects.exists()


def test_the_permission_is_checked_before_anything_else(acting_as: ActingAs) -> None:
    nobody = acting_as()

    with pytest.raises(PermissionDenied):
        _submit(nobody, title="", licence="")


def test_an_article_is_refused_without_the_licence(reader: AuthenticationContext) -> None:
    for licence in ("", "CC-BY-NC-4.0", "all rights reserved"):
        with pytest.raises(InvalidEntryError, match="CC BY 4.0"):
            _submit(reader, licence=licence)

    assert not Article.objects.exists()
    assert _audit() == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("author_name", "   "),
        ("title", ""),
        ("summary", ""),
        ("body", "\n\n"),
        ("author_name", "A" * 121),
        ("title", "T" * 201),
        ("summary", "S" * 601),
        ("body", "B" * 20001),
        ("title", "TEST ‮right to left"),
    ],
)
def test_an_incomplete_or_oversized_article_is_refused(
    reader: AuthenticationContext, field: str, value: str
) -> None:
    with pytest.raises(InvalidEntryError):
        _submit(reader, **{field: value})

    assert not Article.objects.exists()


def test_the_text_is_kept_as_written_apart_from_surrounding_space(
    reader: AuthenticationContext,
) -> None:
    body = "  TEST <b>not markup</b>\n\n  indented line\n"

    article = Article.objects.get(public_id=_submit(reader, body=body))

    assert article.body == "TEST <b>not markup</b>\n\n  indented line"


def test_the_limit_on_articles_from_one_account_is_exact(
    reader: AuthenticationContext,
    other_reader: AuthenticationContext,
    clock: Clock,
    settings: LazySettings,
) -> None:
    assert settings.ARTICLE_SUBMISSION_LIMIT == 5
    assert settings.ARTICLE_SUBMISSION_WINDOW == timedelta(days=1)
    for number in range(settings.ARTICLE_SUBMISSION_LIMIT):
        _submit(reader, title=f"TEST {number}")

    with pytest.raises(InvalidEntryError, match="5 articles within a day"):
        _submit(reader)
    _submit(other_reader)
    clock(settings.ARTICLE_SUBMISSION_WINDOW + timedelta(seconds=1))
    _submit(reader)

    assert Article.objects.filter(author=reader.user).count() == 6


# --- Deciding ------------------------------------------------------------------------------


def test_a_reviewer_publishes_an_article(
    reader: AuthenticationContext, reviewer: AuthenticationContext
) -> None:
    public_id = _submit(reader)

    services.publish_article(actor=reviewer, article_id=public_id)

    decision = ArticleDecision.objects.get()
    assert (decision.decision, decision.reason, decision.decided_by) == (
        "published",
        "",
        reviewer.user,
    )
    assert _audit()[-1] == ("created", "articles.article_decision", decision.public_id)
    assert [entry.public_id for entry in selectors.published_articles(reader)] == [public_id]


def test_an_administrator_reviews_articles_too(
    reader: AuthenticationContext, administrator: AuthenticationContext
) -> None:
    public_id = _submit(reader)

    services.decline_article(actor=administrator, article_id=public_id, reason=REASON)

    assert ArticleDecision.objects.get().decision == "declined"


@pytest.mark.parametrize("role", [Role.READER, Role.RESEARCHER])
def test_a_reader_or_researcher_cannot_decide(
    reader: AuthenticationContext, acting_as: ActingAs, role: Role
) -> None:
    public_id = _submit(reader)
    actor = acting_as(role)

    decisions: tuple[Callable[[], None], ...] = (
        lambda: services.publish_article(actor=actor, article_id=public_id),
        lambda: services.decline_article(actor=actor, article_id=public_id, reason=REASON),
        lambda: services.withdraw_article(actor=actor, article_id=public_id, reason=REASON),
    )
    for decide in decisions:
        with pytest.raises(PermissionDenied):
            decide()

    assert not ArticleDecision.objects.exists()


def test_a_reviewer_on_a_password_alone_cannot_decide(
    reader: AuthenticationContext, acting_as: ActingAs
) -> None:
    public_id = _submit(reader)

    with pytest.raises(PermissionDenied):
        services.publish_article(actor=acting_as(Role.REVIEWER), article_id=public_id)


def test_nobody_decides_about_their_own_article(
    reviewer: AuthenticationContext, acting_as: ActingAs
) -> None:
    public_id = _submit(reviewer)

    with pytest.raises(InvalidEntryError, match="their own article"):
        services.publish_article(actor=reviewer, article_id=public_id)

    services.publish_article(
        actor=acting_as(Role.REVIEWER, second_factor=True), article_id=public_id
    )
    with pytest.raises(InvalidEntryError, match="their own article"):
        services.withdraw_article(actor=reviewer, article_id=public_id, reason=REASON)


def test_an_unknown_article_is_not_found(reviewer: AuthenticationContext) -> None:
    with pytest.raises(RecordNotFoundError):
        services.publish_article(actor=reviewer, article_id=uuid.uuid4())


@pytest.mark.parametrize("decide", ["decline", "withdraw"])
def test_a_decline_or_withdrawal_needs_a_reason(
    reader: AuthenticationContext, reviewer: AuthenticationContext, decide: str
) -> None:
    public_id = _submit(reader)
    if decide == "withdraw":
        services.publish_article(actor=reviewer, article_id=public_id)
    operation = getattr(services, f"{decide}_article")

    with pytest.raises(InvalidEntryError, match="reason"):
        operation(actor=reviewer, article_id=public_id, reason="  ")


def test_one_verdict_and_then_only_a_withdrawal(
    reader: AuthenticationContext, reviewer: AuthenticationContext
) -> None:
    public_id = _submit(reader)
    with pytest.raises(InvalidEntryError, match="cannot be withdrawn"):
        services.withdraw_article(actor=reviewer, article_id=public_id, reason=REASON)

    services.publish_article(actor=reviewer, article_id=public_id)
    with pytest.raises(InvalidEntryError, match="cannot be published"):
        services.publish_article(actor=reviewer, article_id=public_id)
    with pytest.raises(InvalidEntryError, match="cannot be declined"):
        services.decline_article(actor=reviewer, article_id=public_id, reason=REASON)

    services.withdraw_article(actor=reviewer, article_id=public_id, reason=REASON)
    after: tuple[Callable[[], None], ...] = (
        lambda: services.publish_article(actor=reviewer, article_id=public_id),
        lambda: services.withdraw_article(actor=reviewer, article_id=public_id, reason=REASON),
    )
    for decide in after:
        with pytest.raises(InvalidEntryError, match="is withdrawn"):
            decide()

    assert list(ArticleDecision.objects.order_by("id").values_list("decision", flat=True)) == [
        "published",
        "withdrawn",
    ]
    assert selectors.published_articles(reader) == []


def test_nothing_follows_a_decline(
    reader: AuthenticationContext, reviewer: AuthenticationContext
) -> None:
    public_id = _submit(reader)
    services.decline_article(actor=reviewer, article_id=public_id, reason=REASON)

    with pytest.raises(InvalidEntryError, match="is declined"):
        services.publish_article(actor=reviewer, article_id=public_id)

    assert ArticleDecision.objects.count() == 1


# --- Who sees what --------------------------------------------------------------------------


def test_an_article_not_published_exists_only_for_its_author_and_reviewers(
    reader: AuthenticationContext,
    other_reader: AuthenticationContext,
    reviewer: AuthenticationContext,
) -> None:
    public_id = _submit(reader)

    assert selectors.article(other_reader, public_id) is None
    assert selectors.article(reviewer, public_id) is None
    assert selectors.article(reader, public_id) is not None
    assert selectors.article_for_review(reviewer, public_id) is not None
    assert selectors.published_articles(other_reader) == []


def test_a_published_article_is_seen_by_every_reader_without_the_reasons(
    reader: AuthenticationContext,
    other_reader: AuthenticationContext,
    reviewer: AuthenticationContext,
) -> None:
    public_id = _submit(reader)
    services.publish_article(actor=reviewer, article_id=public_id)

    entry = selectors.article(other_reader, public_id)

    assert entry is not None
    assert entry.status == ArticleStatus.PUBLISHED
    assert not entry.is_own
    assert entry.allowed == ()
    assert [decision.label for decision in entry.decisions] == ["Published"]
    assert entry.published_at is not None
    assert entry.licence_deed == "https://creativecommons.org/licenses/by/4.0/"


def test_a_withdrawn_article_disappears_for_readers_and_its_author_sees_why(
    reader: AuthenticationContext,
    other_reader: AuthenticationContext,
    reviewer: AuthenticationContext,
) -> None:
    public_id = _submit(reader)
    services.publish_article(actor=reviewer, article_id=public_id)
    services.withdraw_article(actor=reviewer, article_id=public_id, reason=REASON)

    assert selectors.article(other_reader, public_id) is None
    own = selectors.article(reader, public_id)
    assert own is not None
    assert own.status == ArticleStatus.WITHDRAWN
    assert [decision.reason for decision in own.decisions] == ["", REASON]


def test_the_author_sees_every_own_article_and_the_reason_for_a_decline(
    reader: AuthenticationContext, reviewer: AuthenticationContext
) -> None:
    first = _submit(reader, title="TEST first")
    second = _submit(reader, title="TEST second")
    services.decline_article(actor=reviewer, article_id=first, reason=REASON)

    mine = selectors.articles_of(reader)

    assert [entry.public_id for entry in mine] == [second, first]
    assert [entry.status for entry in mine] == [
        ArticleStatus.AWAITING_REVIEW,
        ArticleStatus.DECLINED,
    ]
    assert mine[1].decisions[0].reason == REASON


def test_reviewers_see_the_queue_oldest_first_and_what_they_may_decide(
    reader: AuthenticationContext,
    reviewer: AuthenticationContext,
    acting_as: ActingAs,
) -> None:
    first = _submit(reader, title="TEST first")
    second = _submit(reader, title="TEST second")
    own = _submit(reviewer, title="TEST own")
    published = _submit(reader, title="TEST published")
    services.publish_article(
        actor=acting_as(Role.REVIEWER, second_factor=True), article_id=published
    )

    waiting = selectors.articles_awaiting_review(reviewer)

    assert [entry.public_id for entry in waiting] == [first, second, own]
    assert [entry.allowed for entry in waiting] == [
        ("published", "declined"),
        ("published", "declined"),
        (),
    ]
    decided = selectors.articles_decided(reviewer)
    assert [(entry.public_id, entry.allowed) for entry in decided] == [(published, ("withdrawn",))]


def test_the_review_pages_are_for_reviewers_only(
    reader: AuthenticationContext, administrator: AuthenticationContext
) -> None:
    public_id = _submit(reader)

    for read in (
        lambda: selectors.articles_awaiting_review(reader),
        lambda: selectors.articles_decided(reader),
        lambda: selectors.article_for_review(reader, public_id),
    ):
        with pytest.raises(PermissionDenied):
            read()
    # An Administrator reviews, and does not read the workspace.
    assert selectors.article_for_review(administrator, public_id) is not None
    with pytest.raises(PermissionDenied):
        selectors.published_articles(administrator)
