"""Write interface of the registry: creating, renaming, deactivating, and reactivating
countries and languages (ADR-0018 point 13, ADR-0019 Increment 2).

Every operation here does five things, in this order, in one transaction
(ADR-0018 point 41): it requires the permission, locks the row it changes,
validates, writes the change, and writes the audit event. Either the change
and its event are both committed or neither is. Nothing is retried, and
nothing is deleted.

The permission is required first, and so before the row is locked. A caller
without it therefore learns nothing about a record, not even whether it
exists. It also means the permission is decided on the state of the account
as it was just before the lock was taken: an account disabled, or a role
revoked, while an operation waits for a row is not seen by that operation.
That is the order ADR-0018 decides, and no second check is made after the
lock.

Nothing here takes a request. An operation is given the authentication
context of whoever is acting, and a record is named by its public
identifier.
"""

import logging
import re
import uuid
from typing import Final

import psycopg.errors
from django.db import IntegrityError, transaction

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts import services as accounts_services
from caipo.accounts.selectors import (
    AuditAction,
    AuditField,
    AuditTargetType,
    AuthenticationContext,
    Permission,
)
from caipo.accounts.services import AuditChange
from caipo.registry.models import NAME_MAX_LENGTH, Country, Language

logger = logging.getLogger(__name__)

# The forms of the codes (ADR-0018 point 6, ADR-0019 points 29 and 30), each
# matched against the whole value. The database checks the same forms for
# itself (`caipo.registry.models`). re.ASCII is not needed for these: a range
# of ASCII letters in a Python pattern is those letters and no others.
_COUNTRY_ALPHA2: Final = re.compile(r"[A-Z]{2}")
_COUNTRY_ALPHA3: Final = re.compile(r"[A-Z]{3}")
_LANGUAGE_CODE: Final = re.compile(r"[a-z]{3}")
_LANGUAGE_SCRIPT_CODE: Final = re.compile(r"[A-Z][a-z]{3}")

# The unique constraints whose violation means that a code is already taken.
# A violation of any other constraint is not that, and is raised as it is.
_COUNTRY_CODE_CONSTRAINTS: Final = frozenset(
    {"registry_country_alpha2_unique", "registry_country_alpha3_unique"}
)
_LANGUAGE_CODE_CONSTRAINTS: Final = frozenset({"registry_language_codes_unique"})


class RegistryError(Exception):
    """The requested change to the registry cannot be made."""


class InvalidEntryError(RegistryError):
    """What was entered is not a valid value for the record."""


class DuplicateCodeError(RegistryError):
    """A record with that code, or that pair of codes, exists already."""


class RecordNotFoundError(RegistryError):
    """No record has that public identifier."""


class NoChangeError(RegistryError):
    """The requested change would change nothing."""


def create_country(
    *, actor: AuthenticationContext, alpha2: str, alpha3: str, name_en: str
) -> uuid.UUID:
    """Create an active country and return its public identifier.

    Preconditions: the actor holds `REGISTRY_REFERENCE_MANAGE`; `alpha2` is
    two capital ASCII letters and `alpha3` three, exactly as given, with
    nothing trimmed or converted; neither code is in use; the name, with
    surrounding whitespace removed, is not empty and is at most 200
    characters. Whether a code is assigned by ISO 3166 is not checked.

    Side effects: one Country and one `created` audit event, in one
    transaction, and a log line once it has committed. The name is stored
    with surrounding whitespace removed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before anything else is examined; InvalidEntryError if a code or
    the name is not valid; DuplicateCodeError if either code is in use,
    including when another transaction took it first. Any other failure of
    the database, or of the audit writer, is raised as it is. In every case
    nothing is stored and no audit event is written.
    """
    try:
        with transaction.atomic():
            accounts_selectors.require_permission(actor, Permission.REGISTRY_REFERENCE_MANAGE)
            _require_form(alpha2, _COUNTRY_ALPHA2, "The alpha-2 code is two capital letters.")
            _require_form(alpha3, _COUNTRY_ALPHA3, "The alpha-3 code is three capital letters.")
            name = _valid_name(name_en)
            if (
                Country.objects.filter(alpha2=alpha2).exists()
                or Country.objects.filter(alpha3=alpha3).exists()
            ):
                raise DuplicateCodeError("A country with one of these codes exists already.")
            country = Country.objects.create(alpha2=alpha2, alpha3=alpha3, name_en=name)
            _record(actor, AuditAction.CREATED, AuditTargetType.COUNTRY, country.public_id)
    except IntegrityError as error:
        if _violated_constraint(error) in _COUNTRY_CODE_CONSTRAINTS:
            raise DuplicateCodeError("A country with one of these codes exists already.") from error
        raise
    _log(actor, AuditAction.CREATED, AuditTargetType.COUNTRY, country.public_id)
    return country.public_id


def rename_country(*, actor: AuthenticationContext, public_id: uuid.UUID, name_en: str) -> None:
    """Change the English name of a country.

    Preconditions: the actor holds `REGISTRY_REFERENCE_MANAGE`; the country
    exists; the name, with surrounding whitespace removed, is not empty, is
    at most 200 characters, and differs from the stored name. A deactivated
    country can be renamed.

    Side effects: the name is overwritten, and one `updated` audit event
    records the old and the new stored name, in one transaction; a log line
    once it has committed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before the country is looked up; RecordNotFoundError if no country
    has the identifier; InvalidEntryError if the name is not valid;
    NoChangeError if the name is the stored one. In every case nothing is
    changed and no audit event is written.
    """
    _rename(actor, Country, AuditTargetType.COUNTRY, public_id, name_en)


def deactivate_country(*, actor: AuthenticationContext, public_id: uuid.UUID) -> None:
    """Deactivate a country. It stays, stays readable, and can be reactivated.

    Preconditions: the actor holds `REGISTRY_REFERENCE_MANAGE`; the country
    exists and is active. Side effects: the active flag is cleared and one
    `deactivated` audit event is written, in one transaction; a log line once
    it has committed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before the country is looked up; RecordNotFoundError if no country
    has the identifier; NoChangeError if it is deactivated already.
    """
    _set_active(actor, Country, AuditTargetType.COUNTRY, public_id, active=False)


def reactivate_country(*, actor: AuthenticationContext, public_id: uuid.UUID) -> None:
    """Reactivate a deactivated country.

    Preconditions, side effects, and errors are those of
    `deactivate_country`, with the flag set, a `reactivated` audit event, and
    NoChangeError if the country is active already.
    """
    _set_active(actor, Country, AuditTargetType.COUNTRY, public_id, active=True)


def create_language(
    *, actor: AuthenticationContext, code: str, script_code: str, name_en: str
) -> uuid.UUID:
    """Create an active language in a script and return its public identifier.

    Preconditions: the actor holds `REGISTRY_REFERENCE_MANAGE`; `code` is
    three lower-case ASCII letters and `script_code` one capital ASCII letter
    followed by three lower-case, exactly as given, with nothing trimmed or
    converted, and no other form is accepted; the pair is not in use; the
    name, with surrounding whitespace removed, is not empty and is at most
    200 characters. Whether a code is assigned by ISO 639-3 or ISO 15924 is
    not checked. The same language code may occur with another script code.

    Side effects: one Language and one `created` audit event, in one
    transaction, and a log line once it has committed. The name is stored
    with surrounding whitespace removed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before anything else is examined; InvalidEntryError if a code or
    the name is not valid; DuplicateCodeError if the pair is in use,
    including when another transaction took it first. Any other failure of
    the database, or of the audit writer, is raised as it is. In every case
    nothing is stored and no audit event is written.
    """
    try:
        with transaction.atomic():
            accounts_selectors.require_permission(actor, Permission.REGISTRY_REFERENCE_MANAGE)
            _require_form(code, _LANGUAGE_CODE, "The language code is three lower-case letters.")
            _require_form(
                script_code,
                _LANGUAGE_SCRIPT_CODE,
                "The script code is one capital letter followed by three lower-case letters.",
            )
            name = _valid_name(name_en)
            if Language.objects.filter(code=code, script_code=script_code).exists():
                raise DuplicateCodeError("A language with this pair of codes exists already.")
            language = Language.objects.create(code=code, script_code=script_code, name_en=name)
            _record(actor, AuditAction.CREATED, AuditTargetType.LANGUAGE, language.public_id)
    except IntegrityError as error:
        if _violated_constraint(error) in _LANGUAGE_CODE_CONSTRAINTS:
            raise DuplicateCodeError(
                "A language with this pair of codes exists already."
            ) from error
        raise
    _log(actor, AuditAction.CREATED, AuditTargetType.LANGUAGE, language.public_id)
    return language.public_id


def rename_language(*, actor: AuthenticationContext, public_id: uuid.UUID, name_en: str) -> None:
    """Change the English name of a language.

    Preconditions, side effects, and errors are those of `rename_country`,
    for a language.
    """
    _rename(actor, Language, AuditTargetType.LANGUAGE, public_id, name_en)


def deactivate_language(*, actor: AuthenticationContext, public_id: uuid.UUID) -> None:
    """Deactivate a language. It stays, stays readable, and can be reactivated.

    Preconditions, side effects, and errors are those of
    `deactivate_country`, for a language.
    """
    _set_active(actor, Language, AuditTargetType.LANGUAGE, public_id, active=False)


def reactivate_language(*, actor: AuthenticationContext, public_id: uuid.UUID) -> None:
    """Reactivate a deactivated language.

    Preconditions, side effects, and errors are those of
    `reactivate_country`, for a language.
    """
    _set_active(actor, Language, AuditTargetType.LANGUAGE, public_id, active=True)


def _rename(
    actor: AuthenticationContext,
    model: type[Country] | type[Language],
    target_type: AuditTargetType,
    public_id: uuid.UUID,
    name_en: str,
) -> None:
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_REFERENCE_MANAGE)
        record = _locked(model, public_id)
        name = _valid_name(name_en)
        old = record.name_en
        if name == old:
            raise NoChangeError("The record has this name already.")
        record.name_en = name
        record.save(update_fields=["name_en"])
        accounts_services.record_audit_event(
            actor=actor,
            action=AuditAction.UPDATED,
            target_type=target_type,
            target_public_id=record.public_id,
            changes=[AuditChange(AuditField.NAME_EN, old, name)],
        )
    _log(actor, AuditAction.UPDATED, target_type, record.public_id)


def _set_active(
    actor: AuthenticationContext,
    model: type[Country] | type[Language],
    target_type: AuditTargetType,
    public_id: uuid.UUID,
    *,
    active: bool,
) -> None:
    action = AuditAction.REACTIVATED if active else AuditAction.DEACTIVATED
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_REFERENCE_MANAGE)
        record = _locked(model, public_id)
        if record.is_active == active:
            raise NoChangeError(
                "The record is active already." if active else "The record is deactivated already."
            )
        record.is_active = active
        record.save(update_fields=["is_active"])
        _record(actor, action, target_type, record.public_id)
    _log(actor, action, target_type, record.public_id)


def _locked(model: type[Country] | type[Language], public_id: uuid.UUID) -> Country | Language:
    """Return the record with this public identifier, locked until the transaction ends.

    Raises RecordNotFoundError if there is none, or if what was given is not
    a UUID: a record is named by its public identifier and by nothing else.
    """
    if not isinstance(public_id, uuid.UUID):
        raise RecordNotFoundError("A record is named by its public identifier.")
    record = model.objects.select_for_update().filter(public_id=public_id).first()
    if record is None:
        raise RecordNotFoundError("No record has this public identifier.")
    return record


def _require_form(value: str, pattern: re.Pattern[str], message: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise InvalidEntryError(message)


def _valid_name(name_en: str) -> str:
    """Return the name as it is stored: with surrounding whitespace removed.

    Raises InvalidEntryError if nothing is left, if it is longer than
    NAME_MAX_LENGTH, or if it holds a NUL character, which PostgreSQL cannot
    store in text.
    """
    if not isinstance(name_en, str):
        raise InvalidEntryError("The English name is text.")
    name = name_en.strip()
    if not name:
        raise InvalidEntryError("The English name is required.")
    if len(name) > NAME_MAX_LENGTH:
        raise InvalidEntryError("The English name is too long.")
    if "\x00" in name:
        raise InvalidEntryError("The English name holds a character that cannot be stored.")
    return name


def _violated_constraint(error: IntegrityError) -> str | None:
    """Return the name of the unique constraint the database refused on, if that is what failed."""
    cause = error.__cause__
    if isinstance(cause, psycopg.errors.UniqueViolation):
        return cause.diag.constraint_name
    return None


def _record(
    actor: AuthenticationContext,
    action: AuditAction,
    target_type: AuditTargetType,
    public_id: uuid.UUID,
) -> None:
    accounts_services.record_audit_event(
        actor=actor,
        action=action,
        target_type=target_type,
        target_public_id=public_id,
        changes=[],
    )


def _log(
    actor: AuthenticationContext,
    action: AuditAction,
    target_type: AuditTargetType,
    public_id: uuid.UUID,
) -> None:
    """Log a change that has been made. The identifier, and never a value."""
    logger.info(
        "Registry record %s",
        action.value,
        extra={
            "event": f"{target_type.value}_{action.value}",
            "public_id": str(public_id),
            "actor_id": actor.user.pk,
        },
    )
