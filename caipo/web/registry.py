"""The two pages of the registry (ADR-0018 points 59 to 61, ADR-0019 points 11 to 16).

A browse page that lists countries and languages, and an entry page on which
an Administrator maintains them. There is no third page: every change is a
POST that answers with the entry page or a redirect to it.

These views handle the request and nothing else. Who may read, who may
change what, what a valid code or name is, and what is recorded are decided
by `caipo.registry` and `caipo.accounts`. A change is made by POST with a
CSRF token, and names its record by the public identifier in the path. Not
showing a form to an account that may not use it is a courtesy and never the
check: each POST view declares the permission, and each service requires it
again for itself.
"""

import uuid
from collections.abc import Callable
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.registry import selectors, services
from caipo.registry.services import (
    DuplicateCodeError,
    InvalidEntryError,
    NoChangeError,
    RecordNotFoundError,
)
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.forms import CountryCreationForm, LanguageCreationForm, RegistryNameForm

INVALID_COUNTRY_MESSAGE = _(
    "Nothing was saved. A country needs an alpha-2 code of two capital letters, an alpha-3"
    " code of three capital letters, and an English name of at most 200 characters."
)
INVALID_LANGUAGE_MESSAGE = _(
    "Nothing was saved. A language needs a language code of three lower-case letters, a script"
    " code of one capital letter followed by three lower-case letters, and an English name of"
    " at most 200 characters."
)
INVALID_NAME_MESSAGE = _("Nothing was saved. Give an English name of at most 200 characters.")
DUPLICATE_COUNTRY_MESSAGE = _("Nothing was saved. A country with one of these codes exists.")
DUPLICATE_LANGUAGE_MESSAGE = _(
    "Nothing was saved. A language with this language code and script code exists."
)
NO_CHANGE_MESSAGE = _("Nothing was changed: the record is already as you asked.")
NOT_FOUND_MESSAGE = _("Nothing was changed: there is no such record.")
SAVED_QUERY = "saved"


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _entry_page(
    request: HttpRequest,
    actor: AuthenticationContext,
    *,
    country_form: CountryCreationForm | None = None,
    language_form: LanguageCreationForm | None = None,
    error: Promise | None = None,
    status: int = 200,
) -> HttpResponse:
    may_manage_reference = accounts_selectors.can(actor, Permission.REGISTRY_REFERENCE_MANAGE)
    context: dict[str, Any] = {
        "may_manage_reference": may_manage_reference,
        "error": error,
        "saved": SAVED_QUERY in request.GET,
    }
    if may_manage_reference:
        context |= {
            "country_form": country_form or CountryCreationForm(prefix="country"),
            "language_form": language_form or LanguageCreationForm(prefix="language"),
            "name_form": RegistryNameForm(),
            "countries": selectors.countries(actor),
            "languages": selectors.languages(actor),
        }
    return render(request, "web/registry_entry.html", context, status=status)


def _saved() -> HttpResponse:
    return HttpResponseRedirect(f"{reverse('registry-entry')}?{SAVED_QUERY}=1")


def _change(
    request: HttpRequest, actor: AuthenticationContext, change: Callable[[], None]
) -> HttpResponse:
    """Make one change to an existing record and answer for it."""
    try:
        change()
    except InvalidEntryError:
        return _entry_page(request, actor, error=INVALID_NAME_MESSAGE, status=400)
    except NoChangeError:
        return _entry_page(request, actor, error=NO_CHANGE_MESSAGE, status=409)
    except RecordNotFoundError:
        return _entry_page(request, actor, error=NOT_FOUND_MESSAGE, status=404)
    return _saved()


@requires(Permission.REGISTRY_READ)
@never_cache
@require_GET
def browse(request: HttpRequest) -> HttpResponse:
    """List the countries and languages of the registry, deactivated ones included."""
    actor = _actor(request)
    context = {
        "countries": selectors.countries(actor),
        "languages": selectors.languages(actor),
        "may_enter": accounts_selectors.can(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE),
    }
    return render(request, "web/registry.html", context)


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@require_GET
def entry(request: HttpRequest) -> HttpResponse:
    """Show the entry page: the country and language forms, or why there are none."""
    return _entry_page(request, _actor(request))


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def create_country(request: HttpRequest) -> HttpResponse:
    """Create a country."""
    actor = _actor(request)
    form = CountryCreationForm(request.POST, prefix="country")
    if not form.is_valid():
        return _entry_page(
            request, actor, country_form=form, error=INVALID_COUNTRY_MESSAGE, status=400
        )
    try:
        services.create_country(
            actor=actor,
            alpha2=form.cleaned_data["alpha2"],
            alpha3=form.cleaned_data["alpha3"],
            name_en=form.cleaned_data["name_en"],
        )
    except InvalidEntryError:
        return _entry_page(
            request, actor, country_form=form, error=INVALID_COUNTRY_MESSAGE, status=400
        )
    except DuplicateCodeError:
        return _entry_page(
            request, actor, country_form=form, error=DUPLICATE_COUNTRY_MESSAGE, status=409
        )
    return _saved()


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def rename_country(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Change the English name of a country."""
    actor = _actor(request)
    form = RegistryNameForm(request.POST)
    if not form.is_valid():
        return _entry_page(request, actor, error=INVALID_NAME_MESSAGE, status=400)
    return _change(
        request,
        actor,
        lambda: services.rename_country(
            actor=actor, public_id=public_id, name_en=form.cleaned_data["name_en"]
        ),
    )


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def deactivate_country(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Deactivate a country."""
    actor = _actor(request)
    return _change(
        request, actor, lambda: services.deactivate_country(actor=actor, public_id=public_id)
    )


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def reactivate_country(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Reactivate a country."""
    actor = _actor(request)
    return _change(
        request, actor, lambda: services.reactivate_country(actor=actor, public_id=public_id)
    )


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def create_language(request: HttpRequest) -> HttpResponse:
    """Create a language in a script."""
    actor = _actor(request)
    form = LanguageCreationForm(request.POST, prefix="language")
    if not form.is_valid():
        return _entry_page(
            request, actor, language_form=form, error=INVALID_LANGUAGE_MESSAGE, status=400
        )
    try:
        services.create_language(
            actor=actor,
            code=form.cleaned_data["code"],
            script_code=form.cleaned_data["script_code"],
            name_en=form.cleaned_data["name_en"],
        )
    except InvalidEntryError:
        return _entry_page(
            request, actor, language_form=form, error=INVALID_LANGUAGE_MESSAGE, status=400
        )
    except DuplicateCodeError:
        return _entry_page(
            request, actor, language_form=form, error=DUPLICATE_LANGUAGE_MESSAGE, status=409
        )
    return _saved()


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def rename_language(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Change the English name of a language."""
    actor = _actor(request)
    form = RegistryNameForm(request.POST)
    if not form.is_valid():
        return _entry_page(request, actor, error=INVALID_NAME_MESSAGE, status=400)
    return _change(
        request,
        actor,
        lambda: services.rename_language(
            actor=actor, public_id=public_id, name_en=form.cleaned_data["name_en"]
        ),
    )


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def deactivate_language(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Deactivate a language."""
    actor = _actor(request)
    return _change(
        request, actor, lambda: services.deactivate_language(actor=actor, public_id=public_id)
    )


@requires(Permission.REGISTRY_REFERENCE_MANAGE)
@never_cache
@csrf_protect
@require_POST
def reactivate_language(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Reactivate a language."""
    actor = _actor(request)
    return _change(
        request, actor, lambda: services.reactivate_language(actor=actor, public_id=public_id)
    )
