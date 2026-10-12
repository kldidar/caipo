"""Fixtures of the registry tests."""

import pytest

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.registry.tests.helpers import ActingAs


@pytest.fixture
def administrator(acting_as: ActingAs) -> AuthenticationContext:
    """Return the context of an Administrator verified with a trusted second factor."""
    return acting_as(Role.ADMINISTRATOR, second_factor=True)
