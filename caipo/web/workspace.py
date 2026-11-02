"""What the demonstrator's pages share (ADR-0020): the acting account, identifiers, options."""

import uuid

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from caipo.accounts.selectors import AuthenticationContext
from caipo.core.entry import DataClassError, InvalidEntryError, RecordNotFoundError
from caipo.registry import selectors as registry_selectors
from caipo.web import sessions
from caipo.web.workspace_forms import Options

# What a service refuses because of what was entered. The page is shown
# again with the reason; anything else is an error of the server.
REFUSED = (InvalidEntryError, RecordNotFoundError, DataClassError)
FORM_ERROR = _("Some fields are missing or not valid. Correct them and try again.")


def actor_of(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def country_options() -> Options:
    return [
        (str(country.public_id), f"{country.name_en} ({country.alpha2})")
        for country in registry_selectors.country_choices()
    ]


def language_options() -> Options:
    return [(str(key), label) for key, label in registry_selectors.language_choices()]


def institution_options() -> Options:
    return [(str(key), label) for key, label in registry_selectors.institution_choices()]
