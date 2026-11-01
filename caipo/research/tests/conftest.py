"""Fixtures of the research tests."""

import pytest

from caipo.accounts.selectors import AuthenticationContext, Role
from caipo.registry.tests.helpers import ActingAs
from caipo.sources.tests.helpers import World, make_world


@pytest.fixture
def world(db: None) -> World:
    return make_world()


@pytest.fixture
def researcher(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.RESEARCHER)


@pytest.fixture
def reader(acting_as: ActingAs) -> AuthenticationContext:
    return acting_as(Role.READER)
