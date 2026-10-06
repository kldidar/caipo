"""Asking for a lost second factor to be recovered, over HTTP (ADR-0017).

The request only. Nothing here authorises one, and nothing does yet.
"""

import logging
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from caipo.accounts import services
from caipo.accounts.models import (
    AuthenticationEvent,
    MfaChallenge,
    MfaRecoveryRequest,
    TotpDevice,
    User,
)
from caipo.accounts.selectors import Role
from caipo.accounts.tests.fixtures import UserFactory, code_at, enrolled_device, logged
from caipo.web import sessions

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type AccountFactory = Callable[..., User]

# Visibly synthetic fixture values.
PASSWORD = "TEST-passphrase-for-fixtures-only"

LOGIN = "/login/"
VERIFY = "/login/verify/"
RECOVER = "/login/verify/recover/"
OWN_PAGE = "/account/second-factor/"

OFFER = 'action="/login/verify/recover/"'
REFUSED = "The request was not accepted."
THROTTLED = "Too many recovery requests."
RECOVERY_EVENTS = ["mfa_recovery_requested", "mfa_recovery_failed"]


@pytest.fixture
def account(user_with_roles: UserFactory) -> AccountFactory:
    """Return a factory for synthetic users with a known password and an active second factor."""

    def make(*roles: Role) -> User:
        user = user_with_roles(*roles)
        user.set_password(PASSWORD)
        user.save()
        enrolled_device(user)
        return user

    return make


def _password_step(client: Client, user: User, **extra: str) -> Any:
    response = client.post(LOGIN, {"email": user.email, "password": PASSWORD, **extra})
    assert response["Location"] == VERIFY
    return response


def _pending(user: User) -> Client:
    client = Client()
    _password_step(client, user)
    return client


def _recorded() -> list[tuple[str, int | None]]:
    return list(
        AuthenticationEvent.objects.filter(event_type__in=RECOVERY_EVENTS)
        .order_by("id")
        .values_list("event_type", "user_id")
    )


def _session(client: Client) -> tuple[str | None, dict[str, Any], Any]:
    """Return the session's key, what it holds, and when it lapses on the server."""
    key = client.session.session_key
    expires = Session.objects.filter(session_key=key).values_list("expire_date", flat=True).first()
    return key, dict(client.session.items()), expires


def _answer(response: Any) -> tuple[int, str, list[str], list[tuple[str, str]]]:
    """Return everything a visitor can observe in a response.

    Two things are left out because they differ between any two responses,
    by design: the CSRF token in the page, which is masked anew each time,
    and the time in the Expires header.
    """
    body = re.sub(
        r'name="csrfmiddlewaretoken" value="[^"]+"',
        'name="csrfmiddlewaretoken" value=""',
        response.content.decode(),
    )
    headers = sorted(
        (name, value)
        for name, value in response.headers.items()
        if name not in ("Content-Length", "Expires")
    )
    return response.status_code, body, sorted(response.cookies.keys()), headers


def _fail_from(source: str, times: int = 10) -> None:
    for _ in range(times):
        services.request_mfa_recovery(challenge="TEST-not-a-challenge", source=source)


# --- Where the offer is shown (point 27) -----------------------------------------------


def test_the_offer_is_on_the_page_that_awaits_the_code(account: AccountFactory) -> None:
    client = _pending(account(Role.ADMINISTRATOR))

    page = client.get(VERIFY).content.decode()

    assert OFFER in page
    assert page.count("csrfmiddlewaretoken") == 3


def test_the_offer_is_the_same_whatever_the_account(account: AccountFactory) -> None:
    pages = [
        _answer(_pending(account(*roles)).get(VERIFY))[1]
        for roles in ((Role.ADMINISTRATOR,), (Role.REVIEWER,), (Role.READER,), ())
    ]

    assert len(set(pages)) == 1
    assert OFFER in pages[0]


def test_the_offer_takes_nothing_but_the_csrf_token(account: AccountFactory) -> None:
    page = _pending(account(Role.ADMINISTRATOR)).get(VERIFY).content.decode()

    form = page[
        page.index("<form", page.index(OFFER) - 40) : page.index("</form>", page.index(OFFER))
    ]
    assert re.findall(r'<input[^>]*name="([^"]+)"', form) == ["csrfmiddlewaretoken"]


@pytest.mark.parametrize("path", [LOGIN, "/password-reset/", "/password-reset/confirm/"])
def test_no_page_that_a_visitor_who_is_not_signed_in_can_reach_offers_recovery(
    client: Client, path: str
) -> None:
    page = client.get(path).content.decode()

    assert "recover" not in page.lower()


def test_a_signed_in_account_is_not_offered_recovery(
    client: Client, user_with_roles: UserFactory
) -> None:
    client.force_login(user_with_roles(Role.READER))

    for path in (LOGIN, OWN_PAGE):
        assert OFFER not in client.get(path).content.decode()


# --- A request that is accepted --------------------------------------------------------


def test_asking_shows_the_number_and_how_long_it_lasts(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)

    response = client.post(RECOVER)

    request = MfaRecoveryRequest.objects.get()
    page = response.content.decode()
    assert response.status_code == 200
    assert request.user == user
    assert f"<strong>{request.pk}</strong>" in page
    assert "30 minutes" in page
    assert "You have not been signed in." in page
    assert _recorded() == [("mfa_recovery_requested", user.pk)]


def test_the_answer_holds_nothing_about_the_account_but_the_number(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)
    challenge = client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"]

    response = client.post(RECOVER)

    page = response.content.decode()
    for forbidden in (user.email, challenge, PASSWORD, "Administrator</", "administrator"):
        assert forbidden not in page, forbidden
    assert "no-store" in response["Cache-Control"]


def test_asking_signs_nobody_in_and_ends_the_pending_sign_in(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)

    client.post(RECOVER)

    assert sessions.PENDING_SIGN_IN_KEY not in client.session
    assert "_auth_user_id" not in client.session
    assert sessions.VERIFIED_DEVICE_KEY not in client.session
    assert client.get(OWN_PAGE).status_code == 403
    # Nothing is left to verify: the code page sends the visitor to sign in.
    assert client.get(VERIFY)["Location"] == LOGIN
    assert client.post(VERIFY, {"code": code_at()})["Location"] == LOGIN
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()


def test_asking_leaves_the_accounts_other_sessions_and_its_device_as_they_were(
    account: AccountFactory,
) -> None:
    user = account(Role.READER, Role.REVIEWER)
    elsewhere = Client()
    _password_step(elsewhere, user)
    assert elsewhere.post(VERIFY, {"code": code_at()}).status_code == 302
    signed_in = _session(elsewhere)
    device = TotpDevice.objects.filter(user=user).values().get()
    stored = User.objects.filter(pk=user.pk).values().get()

    _pending(user).post(RECOVER)

    assert MfaRecoveryRequest.objects.filter(user=user).exists()
    assert _session(elsewhere) == signed_in
    assert elsewhere.get(OWN_PAGE).status_code == 200
    assert TotpDevice.objects.filter(user=user).values().get() == device
    assert User.objects.filter(pk=user.pk).values().get() == stored


def test_the_person_can_sign_in_with_the_device_after_asking(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)
    client.post(RECOVER)

    _password_step(client, user)
    response = client.post(VERIFY, {"code": code_at()})

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_asking_again_gives_another_number(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    first = _pending(user)
    first.post(RECOVER)
    earlier = MfaRecoveryRequest.objects.get().pk

    page = _pending(user).post(RECOVER).content.decode()

    later = MfaRecoveryRequest.objects.get().pk
    assert later > earlier
    assert f"<strong>{later}</strong>" in page
    assert f"<strong>{earlier}</strong>" not in page


# --- The request and the session change together, or not at all ------------------------


def test_an_accepted_request_uses_up_the_challenge_and_the_pending_sign_in_together(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)
    assert MfaChallenge.objects.filter(user=user).exists()
    assert sessions.PENDING_SIGN_IN_KEY in client.session

    response = client.post(RECOVER)

    assert response.status_code == 200
    assert not MfaChallenge.objects.filter(user=user).exists()
    assert sessions.PENDING_SIGN_IN_KEY not in client.session
    assert MfaRecoveryRequest.objects.filter(user=user).count() == 1
    assert _recorded() == [("mfa_recovery_requested", user.pk)]


def test_a_request_that_fails_part_way_leaves_the_database_and_the_session_as_they_were(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)
    client.raise_request_exception = False
    session = _session(client)
    challenge = MfaChallenge.objects.filter(user=user).values().get()
    events = AuthenticationEvent.objects.count()
    reached = []

    def fail(*args: object, **kwargs: object) -> None:
        # Called to record the request: by then the challenge was removed and
        # the request created, inside the transaction.
        reached.append(
            (MfaChallenge.objects.filter(user=user).exists(), MfaRecoveryRequest.objects.count())
        )
        raise RuntimeError("TEST fault")

    monkeypatch.setattr(services, "_record", fail)
    response = client.post(RECOVER)
    monkeypatch.undo()

    assert response.status_code == 500
    assert reached == [(False, 1)]
    # The transaction rolled back: the challenge is the one that was there,
    # no request exists, and no event was committed.
    assert MfaChallenge.objects.filter(user=user).values().get() == challenge
    assert not MfaRecoveryRequest.objects.exists()
    assert AuthenticationEvent.objects.count() == events
    assert _recorded() == []
    # The session was not written either: it still awaits the same code.
    assert _session(client) == session
    assert (
        client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"]
        == session[1][sessions.PENDING_SIGN_IN_KEY]["challenge"]
    )
    assert "_auth_user_id" not in client.session

    # The pending sign-in that was there can still be used.
    client.raise_request_exception = True
    assert client.get(VERIFY).status_code == 200
    assert client.post(VERIFY, {"code": code_at()}).status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_a_request_can_be_made_again_after_one_that_failed_part_way(
    account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)
    client.raise_request_exception = False

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("TEST fault")

    monkeypatch.setattr(services, "_record", fail)
    assert client.post(RECOVER).status_code == 500
    monkeypatch.undo()

    response = client.post(RECOVER)

    assert response.status_code == 200
    assert MfaRecoveryRequest.objects.filter(user=user).count() == 1
    assert sessions.PENDING_SIGN_IN_KEY not in client.session
    assert _recorded() == [("mfa_recovery_requested", user.pk)]


# --- What the request takes from the browser (point 22) --------------------------------


def test_without_a_pending_sign_in_there_is_nothing_to_ask_about(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(**kwargs: object) -> None:
        raise AssertionError("the service was called")

    monkeypatch.setattr(services, "request_mfa_recovery", never)

    response = client.post(RECOVER)

    assert (response.status_code, response["Location"]) == (302, LOGIN)
    assert not AuthenticationEvent.objects.exists()
    assert not MfaRecoveryRequest.objects.exists()


def test_a_signed_in_account_cannot_ask_and_stays_signed_in(
    client: Client, account: AccountFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = account(Role.ADMINISTRATOR)
    client.force_login(user)

    def never(**kwargs: object) -> None:
        raise AssertionError("the service was called")

    monkeypatch.setattr(services, "request_mfa_recovery", never)

    response = client.post(RECOVER, {"email": user.email})

    assert response["Location"] == LOGIN
    assert client.session["_auth_user_id"] == str(user.pk)
    assert not MfaRecoveryRequest.objects.exists()


def test_nothing_the_browser_sends_can_name_the_account(account: AccountFactory) -> None:
    asking = account(Role.ADMINISTRATOR)
    other = account(Role.ADMINISTRATOR)
    other_client = _pending(other)
    other_challenge = other_client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"]
    client = _pending(asking)

    named = {
        "email": other.email,
        "user": str(other.pk),
        "user_id": str(other.pk),
        "account": other.email,
        "challenge": other_challenge,
        "number": "1",
    }
    client.cookies["caipo.mfa_challenge"] = other_challenge
    response = client.post(
        f"{RECOVER}?user={other.pk}&email={other.email}&challenge={other_challenge}",
        named,
        HTTP_X_USER=other.email,
        HTTP_X_CHALLENGE=other_challenge,
        HTTP_X_FORWARDED_FOR="198.51.100.66",
    )

    assert response.status_code == 200
    assert MfaRecoveryRequest.objects.get().user == asking
    assert _recorded() == [("mfa_recovery_requested", asking.pk)]
    # The other account's pending sign-in is untouched.
    assert MfaChallenge.objects.filter(user=other).exists()
    event = AuthenticationEvent.objects.get(event_type="mfa_recovery_requested")
    assert event.source_key == services._key("source", "127.0.0.1")


@pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
def test_a_request_is_only_made_by_post(account: AccountFactory, method: str) -> None:
    user = account(Role.ADMINISTRATOR)
    client = _pending(user)

    response = getattr(client, method)(RECOVER)

    assert response.status_code == 405
    assert not MfaRecoveryRequest.objects.exists()
    assert _recorded() == []
    assert MfaChallenge.objects.filter(user=user).exists()


def test_a_request_needs_a_csrf_token(account: AccountFactory) -> None:
    user = account(Role.ADMINISTRATOR)
    client = Client(enforce_csrf_checks=True)
    token = client.get(LOGIN).cookies["csrftoken"].value
    _password_step(client, user, csrfmiddlewaretoken=token)
    before = _session(client)

    refused = client.post(RECOVER)

    assert refused.status_code == 403
    assert not MfaRecoveryRequest.objects.exists()
    assert _recorded() == []
    assert MfaChallenge.objects.filter(user=user).exists()
    assert _session(client) == before

    token = client.get(VERIFY).cookies["csrftoken"].value
    accepted = client.post(RECOVER, {"csrfmiddlewaretoken": token})
    assert accepted.status_code == 200
    assert MfaRecoveryRequest.objects.filter(user=user).exists()


# --- Refusals (point 72) ---------------------------------------------------------------


def _refusals(account: AccountFactory) -> dict[str, tuple[Client, User]]:
    """Return a pending sign-in for each reason a submission is refused."""
    cases = {
        name: account(Role.ADMINISTRATOR) for name in ("unknown", "lapsed", "used", "replaced")
    }
    cases["ineligible"] = account(Role.READER)
    clients = {name: (_pending(user), user) for name, user in cases.items()}

    MfaChallenge.objects.filter(user=cases["unknown"]).delete()
    MfaChallenge.objects.filter(user=cases["lapsed"]).update(
        created_at=timezone.now() - timedelta(minutes=6)
    )
    used = clients["used"][0].session[sessions.PENDING_SIGN_IN_KEY]["challenge"]
    services.request_mfa_recovery(challenge=used, source="198.51.100.66")
    services.sign_in(email=cases["replaced"].email, password=PASSWORD, source="198.51.100.66")
    return clients


def test_every_refusal_gets_the_same_answer(account: AccountFactory) -> None:
    clients = _refusals(account)

    answers = {name: _answer(client.post(RECOVER)) for name, (client, _) in clients.items()}

    assert len({repr(answer) for answer in answers.values()}) == 1, answers.keys()
    status, body, cookies, _ = answers["unknown"]
    assert status == 200
    assert REFUSED in body
    # The CSRF cookie that every rendered form sets, and no session cookie:
    # the session was not written.
    assert cookies == ["csrftoken"]
    # The page that takes the code, with nothing about the account in it.
    assert OFFER in body
    for _, user in clients.values():
        assert user.email not in body


def test_a_refusal_is_recorded_and_changes_nothing_else(account: AccountFactory) -> None:
    clients = _refusals(account)
    requests = list(MfaRecoveryRequest.objects.values())
    before = {name: _session(client) for name, (client, _) in clients.items()}

    for client, _ in clients.values():
        client.post(RECOVER)

    assert list(MfaRecoveryRequest.objects.values()) == requests
    assert {name: _session(client) for name, (client, _) in clients.items()} == before
    failed = AuthenticationEvent.objects.filter(event_type="mfa_recovery_failed")
    assert {name: failed.filter(user=user).count() for name, (_, user) in clients.items()} == {
        "unknown": 0,
        "used": 0,
        "replaced": 0,
        "lapsed": 1,
        "ineligible": 1,
    }
    assert failed.filter(user__isnull=True).count() == 3
    assert not AuthenticationEvent.objects.filter(event_type="login_success").exists()


def test_an_account_that_is_refused_can_still_sign_in_with_its_device(
    account: AccountFactory,
) -> None:
    user = account(Role.READER)
    client = _pending(user)

    assert REFUSED in client.post(RECOVER).content.decode()

    assert client.post(VERIFY, {"code": code_at()}).status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


# --- The limits answer with 429 (points 74 and 75) -------------------------------------


def test_a_source_that_is_stopped_gets_429_whether_or_not_its_challenge_exists(
    account: AccountFactory,
) -> None:
    existing = _pending(account(Role.ADMINISTRATOR))
    gone_user = account(Role.ADMINISTRATOR)
    gone = _pending(gone_user)
    MfaChallenge.objects.filter(user=gone_user).delete()
    ineligible = _pending(account(Role.READER))
    _fail_from("127.0.0.1")
    events = AuthenticationEvent.objects.count()

    answers = [_answer(client.post(RECOVER)) for client in (existing, gone, ineligible)]

    assert len({repr(answer) for answer in answers}) == 1
    status, body, cookies, _ = answers[0]
    assert status == 429
    assert THROTTLED in body
    assert REFUSED not in body
    # The CSRF cookie that every rendered form sets, and no session cookie:
    # the session was not written.
    assert cookies == ["csrftoken"]
    assert AuthenticationEvent.objects.count() == events
    assert not MfaRecoveryRequest.objects.exists()


def test_an_account_that_is_stopped_gets_the_same_429_as_a_source(
    account: AccountFactory,
) -> None:
    user = account(Role.ADMINISTRATOR)
    for number in range(1, 6):
        challenge = services.sign_in(
            email=user.email, password=PASSWORD, source=f"203.0.113.{number}"
        ).challenge
        assert challenge is not None
        services.request_mfa_recovery(challenge=challenge, source=f"203.0.113.{number}")
    by_account = _answer(_pending(user).post(RECOVER))

    _fail_from("127.0.0.1")
    by_source = _answer(_pending(account(Role.REVIEWER)).post(RECOVER))

    assert by_account[0] == 429
    assert by_account == by_source


@pytest.mark.parametrize("limit", ["source", "account"])
def test_a_throttled_submission_changes_nothing(account: AccountFactory, limit: str) -> None:
    user = account(Role.ADMINISTRATOR)
    if limit == "account":
        for number in range(1, 6):
            challenge = services.sign_in(
                email=user.email, password=PASSWORD, source=f"203.0.113.{number}"
            ).challenge
            assert challenge is not None
            services.request_mfa_recovery(challenge=challenge, source=f"203.0.113.{number}")
    else:
        _fail_from("127.0.0.1")
    client = _pending(user)
    session = _session(client)
    events = list(AuthenticationEvent.objects.order_by("id").values())
    requests = list(MfaRecoveryRequest.objects.values())
    challenges = list(MfaChallenge.objects.values())

    response = client.post(RECOVER)

    assert response.status_code == 429
    # No event, no request removed or made, the challenge and the session as
    # they were.
    assert list(AuthenticationEvent.objects.order_by("id").values()) == events
    assert list(MfaRecoveryRequest.objects.values()) == requests
    assert list(MfaChallenge.objects.values()) == challenges
    assert _session(client) == session
    assert "_auth_user_id" not in client.session
    # The pending sign-in was not used up: the device still completes it.
    assert client.post(VERIFY, {"code": code_at()}).status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_a_throttled_answer_is_not_cached(account: AccountFactory) -> None:
    _fail_from("127.0.0.1")

    response = _pending(account(Role.ADMINISTRATOR)).post(RECOVER)

    assert response.status_code == 429
    assert "no-store" in response["Cache-Control"]


# --- What is logged --------------------------------------------------------------------


def test_nothing_secret_reaches_the_logs_or_a_url(
    account: AccountFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user = account(Role.ADMINISTRATOR)
    refused = account(Role.READER)
    asking, turned_away = _pending(user), _pending(refused)
    challenges = [
        client.session[sessions.PENDING_SIGN_IN_KEY]["challenge"]
        for client in (asking, turned_away)
    ]
    session_keys = [client.session.session_key for client in (asking, turned_away)]
    caplog.clear()

    responses = [asking.post(RECOVER), turned_away.post(RECOVER)]

    written = logged(caplog.records)
    for forbidden in (*challenges, *session_keys, user.email, refused.email, PASSWORD):
        assert forbidden is not None
        assert forbidden not in written, forbidden
    for response in responses:
        assert "Location" not in response
