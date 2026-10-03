"""Putting a test client in the state a sign-in leaves it in, without typing a password."""

from django.test import Client

from caipo.accounts.models import User
from caipo.accounts.tests.fixtures import enrolled_device
from caipo.web import sessions


def signed_in(client: Client, user: User) -> Client:
    """Sign the client in as the user, as after a sign-in with the password alone."""
    client.force_login(user)
    return client


def verified(client: Client, user: User) -> Client:
    """Sign the client in as the user, as after a sign-in with password and second factor.

    The account gets a real, active second factor, and the session notes it
    exactly as the verification page does. The authorization decision is not
    replaced: it checks this session and this device like any other.
    """
    client.force_login(user)
    session = client.session
    session[sessions.VERIFIED_DEVICE_KEY] = enrolled_device(user).pk
    session.save()
    return client
