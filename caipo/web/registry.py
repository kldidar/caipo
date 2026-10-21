"""The two pages of the registry (ADR-0018 points 59 to 61, ADR-0019 points 11 to 16).

A browse page that lists countries, languages, and institutions with their
names, and an entry page. On the entry page every account that reaches it
maintains institutions and their names, and an Administrator also maintains
countries and languages. There is no third page: every change is a POST that
answers with the entry page or a redirect to it.

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
from dataclasses import dataclass
from typing import Any, Literal

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
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
from caipo.registry.selectors import InstitutionEntry, InstitutionNameEntry
from caipo.registry.services import (
    CycleError,
    DeactivatedReferenceError,
    DirectionControlError,
    DuplicateCodeError,
    InvalidEntryError,
    LastNameError,
    NewName,
    NoChangeError,
    RecordNotFoundError,
    RegistryError,
    SuccessionError,
)
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.forms import (
    CountryCreationForm,
    InstitutionForm,
    InstitutionNameDatesForm,
    InstitutionNameForm,
    LanguageCreationForm,
    MarkEnteredInErrorForm,
    Options,
    RegistryNameForm,
)

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
INVALID_INSTITUTION_MESSAGE = _(
    "Nothing was saved. Choose a kind from the list, give each date as a full calendar date or"
    " leave it empty, with valid-from before valid-to, and give a name of at most 500"
    " characters with its language and kind."
)
DEACTIVATED_REFERENCE_MESSAGE = _(
    "Nothing was saved. A deactivated country or language cannot be newly referred to."
)
CYCLE_MESSAGE = _(
    "Nothing was saved. An institution cannot be its own parent or its own successor, directly"
    " or through other institutions."
)
SUCCESSION_MESSAGE = _(
    "Nothing was saved. An institution that names a successor has a valid-to date, and a"
    " successor did not end before the institution it succeeded."
)
DIRECTION_CONTROL_MESSAGE = _(
    "Nothing was saved. The name holds an invisible character that changes the direction of"
    " text (U+202A to U+202E or U+2066 to U+2069). Type the name again without it."
)
MARK_NOT_CONFIRMED_MESSAGE = _(
    "Nothing was changed. A name is marked as entered in error only when the confirmation is"
    " ticked, because the mark cannot be undone."
)
LAST_NAME_MESSAGE = _(
    "Nothing was changed. This is the institution's only name that is not marked as entered in"
    " error. Add the right name first."
)
SAVED_QUERY = "saved"
INSTITUTION_PREFIX = "institution"
FIRST_NAME_PREFIX = "first-name"

# What each refusal of an institution or name operation is answered with. Only
# these are answered: any other error is raised as it is.
INSTITUTION_REFUSALS: dict[type[RegistryError], tuple[Promise, int]] = {
    InvalidEntryError: (INVALID_INSTITUTION_MESSAGE, 400),
    DirectionControlError: (DIRECTION_CONTROL_MESSAGE, 400),
    RecordNotFoundError: (NOT_FOUND_MESSAGE, 404),
    NoChangeError: (NO_CHANGE_MESSAGE, 409),
    DeactivatedReferenceError: (DEACTIVATED_REFERENCE_MESSAGE, 409),
    CycleError: (CYCLE_MESSAGE, 409),
    SuccessionError: (SUCCESSION_MESSAGE, 409),
    LastNameError: (LAST_NAME_MESSAGE, 409),
}


@dataclass(frozen=True)
class _Submitted:
    """What was sent with a refused change to one institution or one name.

    The form it was sent from is shown again with it, as it was typed, and
    with its field errors. `public_id` is the institution's for a change or
    a new name, and the name's for its dates.
    """

    form: Literal["change", "name", "dates"]
    public_id: uuid.UUID
    data: QueryDict

    def data_for(self, form: str, public_id: uuid.UUID) -> QueryDict | None:
        return self.data if self.form == form and self.public_id == public_id else None


@dataclass(frozen=True)
class _NameSection:
    """A name of an institution on the entry page, with its two forms."""

    name: InstitutionNameEntry
    dates_form: InstitutionNameDatesForm
    mark_form: MarkEnteredInErrorForm


@dataclass(frozen=True)
class _InstitutionSection:
    """An institution on the entry page, with the forms that change it and add a name to it."""

    institution: InstitutionEntry
    change_form: InstitutionForm
    name_form: InstitutionNameForm
    names: list[_NameSection]


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _country_options(actor: AuthenticationContext) -> Options:
    deactivated = _("Deactivated")
    return [
        (
            str(country.public_id),
            f"{country.alpha2} · {country.name_en}"
            + ("" if country.is_active else f" · {deactivated}"),
        )
        for country in selectors.countries(actor)
    ]


def _language_options(actor: AuthenticationContext) -> Options:
    deactivated = _("Deactivated")
    return [
        (
            str(language.public_id),
            f"{language.code}-{language.script_code} · {language.name_en}"
            + ("" if language.is_active else f" · {deactivated}"),
        )
        for language in selectors.languages(actor)
    ]


def _institution_sections(
    institutions: list[InstitutionEntry],
    countries: Options,
    languages: Options,
    submitted: _Submitted | None,
) -> list[_InstitutionSection]:
    """Return each institution with its forms, filled in with what is stored.

    The one form a refused change was sent from is filled in with what was
    sent instead.
    """
    everyone = [(str(entry.public_id), entry.label) for entry in institutions]

    def sent(form: str, public_id: uuid.UUID) -> QueryDict | None:
        return submitted.data_for(form, public_id) if submitted is not None else None

    sections = []
    for entry in institutions:
        public_id = str(entry.public_id)
        sections.append(
            _InstitutionSection(
                institution=entry,
                change_form=InstitutionForm(
                    sent("change", entry.public_id),
                    initial={
                        "kind": entry.kind,
                        "country": entry.country,
                        "parent": entry.parent and entry.parent.public_id,
                        "successor": entry.successor and entry.successor.public_id,
                        "valid_from": entry.valid_from,
                        "valid_to": entry.valid_to,
                    },
                    auto_id=f"institution-{public_id}-%s",
                    countries=countries,
                    # It is not offered itself: the service would refuse it.
                    institutions=[option for option in everyone if option[0] != public_id],
                ),
                name_form=InstitutionNameForm(
                    sent("name", entry.public_id),
                    auto_id=f"name-{public_id}-%s",
                    languages=languages,
                ),
                names=[
                    _NameSection(
                        name,
                        InstitutionNameDatesForm(
                            sent("dates", name.public_id),
                            initial={"valid_from": name.valid_from, "valid_to": name.valid_to},
                            auto_id=f"dates-{name.public_id}-%s",
                        ),
                        MarkEnteredInErrorForm(auto_id=f"mark-{name.public_id}-%s"),
                    )
                    for name in entry.names
                ],
            )
        )
    return sections


def _entry_page(
    request: HttpRequest,
    actor: AuthenticationContext,
    *,
    country_form: CountryCreationForm | None = None,
    language_form: LanguageCreationForm | None = None,
    institution_data: QueryDict | None = None,
    submitted: _Submitted | None = None,
    error: Promise | None = None,
    status: int = 200,
) -> HttpResponse:
    """Render the entry page.

    `institution_data` is what was sent with a creation of an institution
    that was refused, and `submitted` what was sent with a refused change to
    an institution or a name, so that each is shown again as it was typed.
    """
    may_manage_reference = accounts_selectors.can(actor, Permission.REGISTRY_REFERENCE_MANAGE)
    institutions = selectors.institutions(actor)
    countries = _country_options(actor)
    languages = _language_options(actor)
    everyone = [(str(entry.public_id), entry.label) for entry in institutions]
    context: dict[str, Any] = {
        "may_manage_reference": may_manage_reference,
        "error": error,
        "saved": SAVED_QUERY in request.GET,
        "institution_form": InstitutionForm(
            institution_data, prefix=INSTITUTION_PREFIX, countries=countries, institutions=everyone
        ),
        "first_name_form": InstitutionNameForm(
            institution_data, prefix=FIRST_NAME_PREFIX, languages=languages
        ),
        "institutions": _institution_sections(institutions, countries, languages, submitted),
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
    except DirectionControlError:
        return _entry_page(request, actor, error=DIRECTION_CONTROL_MESSAGE, status=400)
    except InvalidEntryError:
        return _entry_page(request, actor, error=INVALID_NAME_MESSAGE, status=400)
    except NoChangeError:
        return _entry_page(request, actor, error=NO_CHANGE_MESSAGE, status=409)
    except RecordNotFoundError:
        return _entry_page(request, actor, error=NOT_FOUND_MESSAGE, status=404)
    return _saved()


def _institution_change(
    request: HttpRequest,
    actor: AuthenticationContext,
    change: Callable[[], object],
    submitted: _Submitted | None = None,
) -> HttpResponse:
    """Make one change to an institution or a name, and answer for it."""
    try:
        change()
    except tuple(INSTITUTION_REFUSALS) as error:
        message, status = INSTITUTION_REFUSALS[type(error)]
        return _entry_page(request, actor, submitted=submitted, error=message, status=status)
    return _saved()


@requires(Permission.REGISTRY_READ)
@never_cache
@require_GET
def browse(request: HttpRequest) -> HttpResponse:
    """List the countries, languages, and institutions of the registry, with every name."""
    actor = _actor(request)
    context = {
        "countries": selectors.countries(actor),
        "languages": selectors.languages(actor),
        "institutions": selectors.institutions(actor),
        "may_enter": accounts_selectors.can(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE),
    }
    return render(request, "web/registry.html", context)


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@require_GET
def entry(request: HttpRequest) -> HttpResponse:
    """Show the entry page: the institution forms, and the reference forms to an Administrator."""
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
    except DirectionControlError:
        return _entry_page(
            request, actor, country_form=form, error=DIRECTION_CONTROL_MESSAGE, status=400
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
    except DirectionControlError:
        return _entry_page(
            request, actor, language_form=form, error=DIRECTION_CONTROL_MESSAGE, status=400
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


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@csrf_protect
@require_POST
def create_institution(request: HttpRequest) -> HttpResponse:
    """Create an institution with its first name."""
    actor = _actor(request)
    institution = InstitutionForm(request.POST, prefix=INSTITUTION_PREFIX)
    first_name = InstitutionNameForm(request.POST, prefix=FIRST_NAME_PREFIX)
    # Both are validated, so that every field in error is shown.
    if not all([institution.is_valid(), first_name.is_valid()]):
        return _entry_page(
            request,
            actor,
            institution_data=request.POST,
            error=INVALID_INSTITUTION_MESSAGE,
            status=400,
        )
    attributes, name = institution.cleaned_data, first_name.cleaned_data
    try:
        services.create_institution(
            actor=actor,
            kind=attributes["kind"],
            country=attributes["country"],
            parent=attributes["parent"],
            successor=attributes["successor"],
            valid_from=attributes["valid_from"],
            valid_to=attributes["valid_to"],
            first_name=_new_name(name),
        )
    except tuple(INSTITUTION_REFUSALS) as error:
        message, status = INSTITUTION_REFUSALS[type(error)]
        return _entry_page(
            request, actor, institution_data=request.POST, error=message, status=status
        )
    return _saved()


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@csrf_protect
@require_POST
def change_institution(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Change the kind, country, parent, successor, and validity dates of an institution."""
    actor = _actor(request)
    submitted = _Submitted("change", public_id, request.POST)
    form = InstitutionForm(request.POST)
    if not form.is_valid():
        return _entry_page(
            request, actor, submitted=submitted, error=INVALID_INSTITUTION_MESSAGE, status=400
        )
    attributes = form.cleaned_data
    return _institution_change(
        request,
        actor,
        lambda: services.change_institution(
            actor=actor,
            public_id=public_id,
            kind=attributes["kind"],
            country=attributes["country"],
            parent=attributes["parent"],
            successor=attributes["successor"],
            valid_from=attributes["valid_from"],
            valid_to=attributes["valid_to"],
        ),
        submitted,
    )


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@csrf_protect
@require_POST
def add_institution_name(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Add a name to an institution."""
    actor = _actor(request)
    submitted = _Submitted("name", public_id, request.POST)
    form = InstitutionNameForm(request.POST)
    if not form.is_valid():
        return _entry_page(
            request, actor, submitted=submitted, error=INVALID_INSTITUTION_MESSAGE, status=400
        )
    name = _new_name(form.cleaned_data)
    return _institution_change(
        request,
        actor,
        lambda: services.add_institution_name(actor=actor, institution=public_id, name=name),
        submitted,
    )


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@csrf_protect
@require_POST
def change_institution_name_dates(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Change the validity dates of a name of an institution."""
    actor = _actor(request)
    submitted = _Submitted("dates", public_id, request.POST)
    form = InstitutionNameDatesForm(request.POST)
    if not form.is_valid():
        return _entry_page(
            request, actor, submitted=submitted, error=INVALID_INSTITUTION_MESSAGE, status=400
        )
    dates = form.cleaned_data
    return _institution_change(
        request,
        actor,
        lambda: services.change_institution_name_dates(
            actor=actor,
            public_id=public_id,
            valid_from=dates["valid_from"],
            valid_to=dates["valid_to"],
        ),
        submitted,
    )


@requires(Permission.REGISTRY_INSTITUTIONS_MANAGE)
@never_cache
@csrf_protect
@require_POST
def mark_institution_name_entered_in_error(
    request: HttpRequest, public_id: uuid.UUID
) -> HttpResponse:
    """Mark a name of an institution as entered in error, once the confirmation is ticked."""
    actor = _actor(request)
    if not MarkEnteredInErrorForm(request.POST).is_valid():
        return _entry_page(request, actor, error=MARK_NOT_CONFIRMED_MESSAGE, status=400)
    return _institution_change(
        request,
        actor,
        lambda: services.mark_institution_name_entered_in_error(actor=actor, public_id=public_id),
    )


def _new_name(cleaned: dict[str, Any]) -> NewName:
    return NewName(
        text=cleaned["text"],
        language=cleaned["language"],
        kind=cleaned["kind"],
        valid_from=cleaned["valid_from"],
        valid_to=cleaned["valid_to"],
    )
