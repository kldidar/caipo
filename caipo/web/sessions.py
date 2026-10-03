"""What the server-side session holds about a sign-in, beyond Django's own keys.

The session lives in PostgreSQL; the browser holds only its identifier. Two
things are kept here, and never the second-factor secret or a code:

- while a password has been accepted and a code is awaited, the token of the
  pending challenge. Nobody is signed in during that time.
- once a code has been verified, the identifier of the device it was verified
  against. This is a claim that `caipo.accounts.selectors` checks against the
  database on every decision; by itself it grants nothing.
"""

from dataclasses import dataclass

from django.http import HttpRequest

from caipo.accounts import selectors
from caipo.accounts.selectors import AuthenticationContext

PENDING_SIGN_IN_KEY = "caipo.mfa_challenge"
VERIFIED_DEVICE_KEY = "caipo.mfa_verified_device"


@dataclass(frozen=True)
class PendingSignIn:
    challenge: str
    # Where to go once signed in: a path on this site, or nothing. Checked
    # again before it is followed.
    destination: str


def authentication_context(request: HttpRequest) -> AuthenticationContext | None:
    """Return the context the request acts in, or None for an anonymous visitor.

    Built from the account Django's session authentication established and
    from this session's own record. Nothing else in the request is consulted.
    """
    return selectors.authentication_context(
        request.user, verified_device_id=request.session.get(VERIFIED_DEVICE_KEY)
    )


def begin_pending_sign_in(request: HttpRequest, *, challenge: str, destination: str) -> None:
    """Replace the session with one that only awaits a second-factor code.

    Whoever was signed in is signed out, and the session key is new, so a key
    known before the password was typed does not lead to the pending state.
    """
    request.session.flush()
    request.session[PENDING_SIGN_IN_KEY] = {"challenge": challenge, "destination": destination}


def pending_sign_in(request: HttpRequest) -> PendingSignIn | None:
    """Return the sign-in this session is in the middle of, if any."""
    pending = request.session.get(PENDING_SIGN_IN_KEY)
    if not isinstance(pending, dict):
        return None
    challenge, destination = pending.get("challenge"), pending.get("destination")
    if not isinstance(challenge, str) or not isinstance(destination, str):
        return None
    return PendingSignIn(challenge, destination)


def end_pending_sign_in(request: HttpRequest) -> None:
    request.session.pop(PENDING_SIGN_IN_KEY, None)


def record_verified_second_factor(request: HttpRequest, context: AuthenticationContext) -> None:
    """Note in the session which device a code was verified against."""
    request.session[VERIFIED_DEVICE_KEY] = context.mfa_device_id


def forget_verified_second_factor(request: HttpRequest) -> None:
    request.session.pop(VERIFIED_DEVICE_KEY, None)
