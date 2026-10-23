"""Write interface of the registry: the eleven write rows of ADR-0018 point 13.

Countries and languages are created, renamed, deactivated, and reactivated
(ADR-0019 Increment 2). Institutions are created with their first name and
changed; their names are added, have their dates changed, and are marked as
entered in error (ADR-0019 Increment 3).

Every operation here does five things, in this order, in one transaction
(ADR-0018 point 41): it requires the permission, locks the row it changes,
validates, writes the change, and writes the audit event. Either the change
and its event are both committed or neither is. Nothing is retried, and
nothing is deleted.

Where a rule depends on rows other than the one changed, more is locked
(ADR-0018 point 23, and the owner decision of 2026-10-20 that extends it to
the two other rules of that kind). A change to an institution's parent,
successor, or valid-to date, and the creation of an institution that names
a successor, take the succession lock: one such change at a time. Marking a
name locks its institution's row as well as the name's.

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
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

import psycopg.errors
from django.db import IntegrityError, connection, transaction

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
from caipo.registry.models import (
    INSTITUTION_NAME_MAX_LENGTH,
    NAME_MAX_LENGTH,
    Country,
    Institution,
    InstitutionKind,
    InstitutionName,
    InstitutionNameKind,
    Language,
)

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

# The invisible characters that embed, override, or isolate a direction of
# text: U+202A to U+202E and U+2066 to U+2069. Inside a name they can make it
# read differently from the characters it holds, and no name of a body needs
# them, so a name that holds one is refused (diagnostic of 2026-10-20, L5).
# The implicit marks U+200E, U+200F, and U+061C reorder nothing around them,
# can be needed in right-to-left text, and are allowed.
_DIRECTION_CONTROLS: Final = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


class RegistryError(Exception):
    """The requested change to the registry cannot be made."""


class InvalidEntryError(RegistryError):
    """What was entered is not a valid value for the record."""


class DirectionControlError(InvalidEntryError):
    """A name holds an invisible character that sets a direction of text.

    These are the characters that embed, override, or isolate a direction:
    U+202A to U+202E and U+2066 to U+2069.
    """


class DuplicateCodeError(RegistryError):
    """A record with that code, or that pair of codes, exists already."""


class RecordNotFoundError(RegistryError):
    """No record has that public identifier."""


class NoChangeError(RegistryError):
    """The requested change would change nothing."""


class DeactivatedReferenceError(RegistryError):
    """A deactivated country or language cannot be newly referred to."""


class CycleError(RegistryError):
    """The change would make an institution its own parent or successor, directly or not."""


class SuccessionError(RegistryError):
    """The change would break a rule of succession.

    An institution that names a successor has a valid-to date, and where both
    valid-to dates are known, the successor did not end before its
    predecessor did.
    """


class LastNameError(RegistryError):
    """The name is the only one of its institution not marked as entered in error."""


@dataclass(frozen=True)
class NewName:
    """A name to add to an institution, as it is entered.

    The language is named by its public identifier. Dates are full calendar
    dates, or None where they are not known to the day.
    """

    text: str
    language: uuid.UUID
    kind: str
    valid_from: date | None = None
    valid_to: date | None = None


def create_country(
    *, actor: AuthenticationContext, alpha2: str, alpha3: str, name_en: str
) -> uuid.UUID:
    """Create an active country and return its public identifier.

    Preconditions: the actor holds `REGISTRY_REFERENCE_MANAGE`; `alpha2` is
    two capital ASCII letters and `alpha3` three, exactly as given, with
    nothing trimmed or converted; neither code is in use; the name, with
    surrounding whitespace removed, is not empty, is at most 200
    characters, and holds no direction control (U+202A to U+202E, U+2066 to
    U+2069). Whether a code is assigned by ISO 3166 is not checked.

    Side effects: one Country and one `created` audit event, in one
    transaction, and a log line once it has committed. The name is stored
    with surrounding whitespace removed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before anything else is examined; InvalidEntryError if a code or
    the name is not valid, DirectionControlError (a kind of it) if the name
    holds a direction control; DuplicateCodeError if either code is in use,
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
    at most 200 characters, holds no direction control (U+202A to U+202E,
    U+2066 to U+2069), and differs from the stored name. A deactivated
    country can be renamed.

    Side effects: the name is overwritten, and one `updated` audit event
    records the old and the new stored name, in one transaction; a log line
    once it has committed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before the country is looked up; RecordNotFoundError if no country
    has the identifier; InvalidEntryError if the name is not valid,
    DirectionControlError (a kind of it) if it holds a direction control;
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
    name, with surrounding whitespace removed, is not empty, is at most 200
    characters, and holds no direction control (U+202A to U+202E, U+2066 to
    U+2069). Whether a code is assigned by ISO 639-3 or ISO 15924 is
    not checked. The same language code may occur with another script code.

    Side effects: one Language and one `created` audit event, in one
    transaction, and a log line once it has committed. The name is stored
    with surrounding whitespace removed.

    Raises PermissionDenied if the actor may not maintain the reference
    lists, before anything else is examined; InvalidEntryError if a code or
    the name is not valid, DirectionControlError (a kind of it) if the name
    holds a direction control; DuplicateCodeError if the pair is in use,
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


def create_institution(
    *,
    actor: AuthenticationContext,
    kind: str,
    first_name: NewName,
    country: uuid.UUID | None = None,
    parent: uuid.UUID | None = None,
    successor: uuid.UUID | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> uuid.UUID:
    """Create an institution together with its first name, and return its public identifier.

    Preconditions: the actor holds `REGISTRY_INSTITUTIONS_MANAGE`; the kind
    is one of InstitutionKind; the country, the parent, and the successor
    are each empty or the public identifier of a record that exists, and the
    country is active; each date is a calendar date or empty, and where both
    are known valid-from is before valid-to; an institution that names a
    successor has a valid-to date, and where the successor's valid-to date is
    known it is not before this one's. The first name is valid as for
    `add_institution_name`.

    Side effects: one Institution, one InstitutionName, and two `created`
    audit events, the institution's and then the name's, in one transaction,
    and a log line for each once it has committed. A creation that names a
    successor holds the succession lock while it decides.

    Raises PermissionDenied if the actor may not maintain institutions,
    before anything else is examined; InvalidEntryError if a kind, a date,
    or the name is not valid; RecordNotFoundError if a country, language,
    parent, or successor named does not exist; DeactivatedReferenceError if
    the country or the language is deactivated; SuccessionError if a rule of
    succession is not met. Any other failure of the database, or of the
    audit writer, is raised as it is. In every case nothing is stored and no
    audit event is written.
    """
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE)
        if successor is not None:
            _take_succession_lock()
        chosen = _valid_attributes(
            kind=kind,
            country=country,
            parent=parent,
            successor=successor,
            valid_from=valid_from,
            valid_to=valid_to,
            current=None,
        )
        first = _valid_new_name(first_name)
        _require_succession(None, chosen.successor, chosen.valid_to)
        institution = Institution.objects.create(
            kind=chosen.kind,
            country=chosen.country,
            parent=chosen.parent,
            successor=chosen.successor,
            valid_from=chosen.valid_from,
            valid_to=chosen.valid_to,
        )
        name = _create_name(institution, first)
        _record(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION, institution.public_id)
        _record(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION_NAME, name.public_id)
    _log(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION, institution.public_id)
    _log(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION_NAME, name.public_id)
    return institution.public_id


def change_institution(
    *,
    actor: AuthenticationContext,
    public_id: uuid.UUID,
    kind: str,
    country: uuid.UUID | None,
    parent: uuid.UUID | None,
    successor: uuid.UUID | None,
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    """Set the kind, country, parent, successor, and validity dates of an institution.

    Every attribute is given, as it is to be: one left empty is cleared.

    Preconditions: the actor holds `REGISTRY_INSTITUTIONS_MANAGE`; the
    institution exists; what is given is valid as for `create_institution`,
    except that a country already referred to may stay when it has been
    deactivated; at least one attribute differs from what is stored; neither
    the chain of parents nor the chain of successors would come back to this
    institution; where the valid-to dates of this institution and of an
    institution that names it as successor are both known, this one's is not
    before the other's.

    Side effects: the attributes are overwritten, and one `updated` audit
    event records the old and the new value of each that changed, in one
    transaction; a log line once it has committed. A change of the parent,
    the successor, or the valid-to date holds the succession lock while it
    decides.

    Raises PermissionDenied if the actor may not maintain institutions,
    before the institution is looked up; RecordNotFoundError if no
    institution has the identifier, or a country, parent, or successor named
    does not exist; InvalidEntryError if a kind or a date is not valid;
    DeactivatedReferenceError if a country newly referred to is deactivated;
    NoChangeError if nothing would change; CycleError if a chain would come
    back to the institution; SuccessionError if a rule of succession is not
    met. In every case nothing is changed and no audit event is written.
    """
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE)
        institution = _locked_institution(public_id)
        chosen = _valid_attributes(
            kind=kind,
            country=country,
            parent=parent,
            successor=successor,
            valid_from=valid_from,
            valid_to=valid_to,
            current=institution,
        )
        changed = list(_institution_changes(institution, chosen))
        if not changed:
            raise NoChangeError("The institution is already as asked.")
        fields = {change.field for change in changed}
        if fields & {AuditField.PARENT, AuditField.SUCCESSOR, AuditField.VALID_TO}:
            _take_succession_lock()
            _require_no_cycle(institution.pk, chosen.parent, "parent")
            _require_no_cycle(institution.pk, chosen.successor, "successor")
            _require_succession(institution.pk, chosen.successor, chosen.valid_to)
        institution.kind = chosen.kind
        institution.country = chosen.country
        institution.parent = chosen.parent
        institution.successor = chosen.successor
        institution.valid_from = chosen.valid_from
        institution.valid_to = chosen.valid_to
        institution.save(
            update_fields=["kind", "country", "parent", "successor", "valid_from", "valid_to"]
        )
        accounts_services.record_audit_event(
            actor=actor,
            action=AuditAction.UPDATED,
            target_type=AuditTargetType.INSTITUTION,
            target_public_id=institution.public_id,
            changes=changed,
        )
    _log(actor, AuditAction.UPDATED, AuditTargetType.INSTITUTION, institution.public_id)


def add_institution_name(
    *, actor: AuthenticationContext, institution: uuid.UUID, name: NewName
) -> uuid.UUID:
    """Add a name to an institution and return the name's public identifier.

    Preconditions: the actor holds `REGISTRY_INSTITUTIONS_MANAGE`; the
    institution exists; the text, with surrounding whitespace removed and in
    Unicode Normalization Form C, is not empty, is at most 500 characters,
    and holds no NUL character and no direction control (U+202A to U+202E,
    U+2066 to U+2069); the language exists and is active; the kind
    is one of InstitutionNameKind; each date is a calendar date or empty, and
    where both are known valid-from is before valid-to. The same text may be
    added again.

    Side effects: one InstitutionName and one `created` audit event, in one
    transaction; a log line once it has committed. The text is stored as
    described above, and is otherwise as entered.

    Raises PermissionDenied if the actor may not maintain institutions,
    before anything else is examined; RecordNotFoundError if the
    institution or the language does not exist; InvalidEntryError if the
    text, the kind, or a date is not valid, DirectionControlError (a kind of
    it) if the text holds a direction control; DeactivatedReferenceError if the
    language is deactivated. In every case nothing is stored and no audit
    event is written.
    """
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE)
        owner = _institution(institution)
        added = _create_name(owner, _valid_new_name(name))
        _record(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION_NAME, added.public_id)
    _log(actor, AuditAction.CREATED, AuditTargetType.INSTITUTION_NAME, added.public_id)
    return added.public_id


def change_institution_name_dates(
    *,
    actor: AuthenticationContext,
    public_id: uuid.UUID,
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    """Set the two validity dates of an institution's name. Nothing else of a name changes.

    Both dates are given, as they are to be: one left empty is cleared.

    Preconditions: the actor holds `REGISTRY_INSTITUTIONS_MANAGE`; the name
    exists; each date is a calendar date or empty, and where both are known
    valid-from is before valid-to; at least one differs from what is stored.

    Side effects: the dates are overwritten, and one `updated` audit event
    records the old and the new value of each that changed, in one
    transaction; a log line once it has committed.

    Raises PermissionDenied if the actor may not maintain institutions,
    before the name is looked up; RecordNotFoundError if no name has the
    identifier; InvalidEntryError if a date is not valid; NoChangeError if
    neither date would change. In every case nothing is changed and no
    audit event is written.
    """
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE)
        name = _locked_name(public_id)
        start, end = _valid_period(valid_from, valid_to)
        changed = [
            AuditChange(field, old, new)
            for field, old, new in (
                (AuditField.VALID_FROM, name.valid_from, start),
                (AuditField.VALID_TO, name.valid_to, end),
            )
            if old != new
        ]
        if not changed:
            raise NoChangeError("The name has these dates already.")
        name.valid_from, name.valid_to = start, end
        name.save(update_fields=["valid_from", "valid_to"])
        accounts_services.record_audit_event(
            actor=actor,
            action=AuditAction.UPDATED,
            target_type=AuditTargetType.INSTITUTION_NAME,
            target_public_id=name.public_id,
            changes=changed,
        )
    _log(actor, AuditAction.UPDATED, AuditTargetType.INSTITUTION_NAME, name.public_id)


def mark_institution_name_entered_in_error(
    *, actor: AuthenticationContext, public_id: uuid.UUID
) -> None:
    """Mark a name as entered in error. The mark is never cleared.

    A marked name stays and stays readable, and is no longer a name of its
    institution. A mark set by mistake is answered by adding the name again.

    Preconditions: the actor holds `REGISTRY_INSTITUTIONS_MANAGE`; the name
    exists and is not marked; its institution has another name that is not
    marked.

    Side effects: the mark is set, and one `marked_entered_in_error` audit
    event is written, in one transaction; a log line once it has committed.
    The institution's row is locked as well as the name's, so that two names
    of one institution are never marked at once.

    Raises PermissionDenied if the actor may not maintain institutions,
    before the name is looked up; RecordNotFoundError if no name has the
    identifier; NoChangeError if it is marked already; LastNameError if it
    is its institution's only name that is not marked. In every case
    nothing is changed and no audit event is written.
    """
    with transaction.atomic():
        accounts_selectors.require_permission(actor, Permission.REGISTRY_INSTITUTIONS_MANAGE)
        _require_identifier(public_id)
        owner = (
            InstitutionName.objects.filter(public_id=public_id)
            .values_list("institution_id", flat=True)
            .first()
        )
        if owner is None:
            raise RecordNotFoundError("No record has this public identifier.")
        # The institution first, then the name: every operation that holds
        # both takes them in this order.
        Institution.objects.select_for_update(no_key=True).filter(pk=owner).get()
        name = _locked_name(public_id)
        if name.entered_in_error:
            raise NoChangeError("The name is marked as entered in error already.")
        if (
            not InstitutionName.objects.filter(institution_id=owner, entered_in_error=False)
            .exclude(pk=name.pk)
            .exists()
        ):
            raise LastNameError(
                "This is the institution's only name not marked as entered in error."
            )
        name.entered_in_error = True
        name.save(update_fields=["entered_in_error"])
        _record(
            actor,
            AuditAction.MARKED_ENTERED_IN_ERROR,
            AuditTargetType.INSTITUTION_NAME,
            name.public_id,
        )
    _log(actor, AuditAction.MARKED_ENTERED_IN_ERROR, AuditTargetType.INSTITUTION_NAME, public_id)


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


@dataclass(frozen=True)
class _Attributes:
    """The attributes of an institution, validated, with each reference resolved to its record."""

    kind: str
    country: Country | None
    parent: Institution | None
    successor: Institution | None
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True)
class _ValidName:
    """A name to store, validated, with its language resolved to its record."""

    text: str
    language: Language
    kind: str
    valid_from: date | None
    valid_to: date | None


def _valid_attributes(
    *,
    kind: str,
    country: uuid.UUID | None,
    parent: uuid.UUID | None,
    successor: uuid.UUID | None,
    valid_from: date | None,
    valid_to: date | None,
    current: Institution | None,
) -> _Attributes:
    """Return what an institution is to be, from what was entered.

    `current` is the institution as it is stored, or None for a new one: a
    country it already refers to may stay when it has been deactivated.

    Raises InvalidEntryError, RecordNotFoundError, or
    DeactivatedReferenceError. Rules that depend on other institutions are
    not checked here.
    """
    if not isinstance(kind, str) or kind not in InstitutionKind.values:
        raise InvalidEntryError("The kind is not one of the kinds of institution.")
    start, end = _valid_period(valid_from, valid_to)
    chosen_country: Country | None = None
    if country is not None:
        chosen_country = _found_country(country)
        already = current is not None and current.country_id == chosen_country.pk
        if not chosen_country.is_active and not already:
            raise DeactivatedReferenceError("A deactivated country cannot be newly referred to.")
    return _Attributes(
        kind=kind,
        country=chosen_country,
        parent=None if parent is None else _institution(parent),
        successor=None if successor is None else _institution(successor),
        valid_from=start,
        valid_to=end,
    )


def _valid_new_name(name: NewName) -> _ValidName:
    """Return a name as it is stored, from what was entered.

    The text has surrounding whitespace removed and is put into Unicode
    Normalization Form C, and is otherwise as entered. Raises
    InvalidEntryError, RecordNotFoundError, or DeactivatedReferenceError.
    """
    if not isinstance(name, NewName):
        raise InvalidEntryError("A name is entered as a NewName.")
    if not isinstance(name.text, str):
        raise InvalidEntryError("The name is text.")
    text = unicodedata.normalize("NFC", name.text.strip())
    if not text:
        raise InvalidEntryError("The name is required.")
    if len(text) > INSTITUTION_NAME_MAX_LENGTH:
        raise InvalidEntryError("The name is too long.")
    if "\x00" in text:
        raise InvalidEntryError("The name holds a character that cannot be stored.")
    _require_no_direction_control(text)
    if not isinstance(name.kind, str) or name.kind not in InstitutionNameKind.values:
        raise InvalidEntryError("The kind is not one of the kinds of name.")
    start, end = _valid_period(name.valid_from, name.valid_to)
    if not isinstance(name.language, uuid.UUID):
        raise RecordNotFoundError("A record is named by its public identifier.")
    language = Language.objects.filter(public_id=name.language).first()
    if language is None:
        raise RecordNotFoundError("No language has this public identifier.")
    if not language.is_active:
        raise DeactivatedReferenceError("A deactivated language cannot be newly referred to.")
    return _ValidName(text, language, name.kind, start, end)


def _create_name(institution: Institution, name: _ValidName) -> InstitutionName:
    return InstitutionName.objects.create(
        institution=institution,
        text=name.text,
        language=name.language,
        kind=name.kind,
        valid_from=name.valid_from,
        valid_to=name.valid_to,
    )


def _valid_period(
    valid_from: date | None, valid_to: date | None
) -> tuple[date | None, date | None]:
    """Return the two dates of a validity period, checked.

    Raises InvalidEntryError if either is neither empty nor a calendar date
    (a date with a time of day is refused), or if both are known and
    valid-from is not before valid-to: the period is half-open.
    """
    for value in (valid_from, valid_to):
        if value is not None and (not isinstance(value, date) or isinstance(value, datetime)):
            raise InvalidEntryError("A date is a calendar date, or empty where it is not known.")
    if valid_from is not None and valid_to is not None and valid_from >= valid_to:
        raise InvalidEntryError("Valid-from is before valid-to.")
    return valid_from, valid_to


def _institution_changes(institution: Institution, chosen: _Attributes) -> Iterator[AuditChange]:
    """Yield each attribute that would change, with its old and its new value.

    A reference is given as the public identifier of the record referred to.
    """
    for field, old, new in (
        (AuditField.KIND, institution.kind, chosen.kind),
        (AuditField.COUNTRY, _identifier(institution.country), _identifier(chosen.country)),
        (AuditField.PARENT, _identifier(institution.parent), _identifier(chosen.parent)),
        (AuditField.SUCCESSOR, _identifier(institution.successor), _identifier(chosen.successor)),
        (AuditField.VALID_FROM, institution.valid_from, chosen.valid_from),
        (AuditField.VALID_TO, institution.valid_to, chosen.valid_to),
    ):
        if old != new:
            yield AuditChange(field, old, new)


def _identifier(record: Country | Institution | None) -> uuid.UUID | None:
    return None if record is None else record.public_id


def _take_succession_lock() -> None:
    """Hold, until the transaction ends, the lock that admits one change of succession at a time.

    Whether a cycle forms, and whether a successor ended before its
    predecessor, depend on institutions other than the one changed, so
    locking that one row is not enough (ADR-0018 point 23). As ADR-0012
    point 12 does for role changes, this is a lock on the table, in a mode
    that conflicts with itself and with every insert and update of an
    institution, and not with reads or with row locks. A row of an
    institution is locked FOR NO KEY UPDATE, so that the deferred check of a
    foreign key that refers to it, which another transaction holding this
    lock may have to make, is never made to wait for it.
    """
    with connection.cursor() as cursor:
        cursor.execute("LOCK TABLE registry_institution IN SHARE ROW EXCLUSIVE MODE")


def _require_no_cycle(subject: int, start: Institution | None, link: str) -> None:
    """Raise CycleError if following `link` from `start` comes back to the subject.

    The chain is read afresh, after the succession lock has been taken.
    """
    seen: set[int] = set()
    current: int | None = None if start is None else start.pk
    while current is not None and current not in seen:
        if current == subject:
            raise CycleError("The chain would come back to this institution.")
        seen.add(current)
        current = Institution.objects.values_list(f"{link}_id", flat=True).get(pk=current)


def _require_succession(
    subject: int | None, successor: Institution | None, valid_to: date | None
) -> None:
    """Raise SuccessionError unless the rules of succession hold (ADR-0018 point 22).

    An institution that names a successor has a valid-to date; where both
    are known, the successor's valid-to date is not before its own; and the
    same holds between it and each institution that names it as successor.
    The dates of the others are read afresh, after the succession lock has
    been taken.
    """
    if successor is not None:
        if valid_to is None:
            raise SuccessionError("An institution that names a successor has a valid-to date.")
        ends = Institution.objects.values_list("valid_to", flat=True).get(pk=successor.pk)
        if ends is not None and ends < valid_to:
            raise SuccessionError("The successor ended before this institution did.")
    if (
        subject is not None
        and valid_to is not None
        and Institution.objects.filter(successor_id=subject, valid_to__gt=valid_to).exists()
    ):
        raise SuccessionError("An institution that this one succeeded ended after it.")


def _found_country(public_id: uuid.UUID) -> Country:
    _require_identifier(public_id)
    country = Country.objects.filter(public_id=public_id).first()
    if country is None:
        raise RecordNotFoundError("No country has this public identifier.")
    return country


def _institution(public_id: uuid.UUID) -> Institution:
    """Return the institution with this public identifier, without a lock."""
    _require_identifier(public_id)
    institution = Institution.objects.filter(public_id=public_id).first()
    if institution is None:
        raise RecordNotFoundError("No institution has this public identifier.")
    return institution


def _locked_institution(public_id: uuid.UUID) -> Institution:
    """Return the institution with this public identifier, locked until the transaction ends.

    FOR NO KEY UPDATE: see `_take_succession_lock`.
    """
    _require_identifier(public_id)
    institution = (
        Institution.objects.select_for_update(no_key=True).filter(public_id=public_id).first()
    )
    if institution is None:
        raise RecordNotFoundError("No institution has this public identifier.")
    return institution


def _locked_name(public_id: uuid.UUID) -> InstitutionName:
    _require_identifier(public_id)
    name = InstitutionName.objects.select_for_update().filter(public_id=public_id).first()
    if name is None:
        raise RecordNotFoundError("No name has this public identifier.")
    return name


def _require_identifier(public_id: object) -> None:
    if not isinstance(public_id, uuid.UUID):
        raise RecordNotFoundError("A record is named by its public identifier.")


def _require_form(value: str, pattern: re.Pattern[str], message: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise InvalidEntryError(message)


def _valid_name(name_en: str) -> str:
    """Return the name as it is stored: with surrounding whitespace removed.

    Raises InvalidEntryError if nothing is left, if it is longer than
    NAME_MAX_LENGTH, or if it holds a NUL character, which PostgreSQL cannot
    store in text; DirectionControlError if it holds a direction control.
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
    _require_no_direction_control(name)
    return name


def _require_no_direction_control(text: str) -> None:
    if not _DIRECTION_CONTROLS.isdisjoint(text):
        raise DirectionControlError(
            "The name holds an invisible character that changes the direction of text."
        )


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
