"""The Country and Language services: what they accept, refuse, store, and record
(ADR-0018 points 6, 7, 13, 18, 35, and 41 to 43; ADR-0019 points 29 to 32).

Who may call them is in test_permissions.py, and what the database refuses by
itself in test_models.py.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from caipo.accounts.models import AuditEvent, AuditEventChange
from caipo.accounts.selectors import AuthenticationContext
from caipo.core.correlation import correlation_scope
from caipo.registry import selectors, services
from caipo.registry.models import Country, Language
from caipo.registry.services import (
    DuplicateCodeError,
    InvalidEntryError,
    NoChangeError,
    RecordNotFoundError,
)
from caipo.registry.tests.helpers import (
    COUNTRIES,
    LANGUAGES,
    UNKNOWN,
    changes,
    events,
    stored,
)

pytestmark = [pytest.mark.services, pytest.mark.django_db]

type Create = Callable[..., uuid.UUID]
type Change = Callable[..., None]

# What is not a capital ASCII letter, and what is not a lower-case one, each
# to stand where one is required.
NOT_A_CAPITAL = ["x", "Х", "Χ", "Ｘ", "İ", "Å", "1", " ", "-", "\n"]
NOT_LOWER_CASE = ["Q", "ԛ", "ｑ", "ı", "å", "ß", "1", " ", "-", "\n"]

BAD_ALPHA2 = [f"{bad}A" for bad in NOT_A_CAPITAL] + [
    "XA\n", "XA ", " XA", "X", "", "XAA", "xa", "Xa",
]  # fmt: skip
BAD_ALPHA3 = [f"{bad}AA" for bad in NOT_A_CAPITAL] + [
    "XAA\n", "XAA ", " XAA", "XA", "", "XAAA", "xaa", "Xaa",
]  # fmt: skip
BAD_LANGUAGE_CODE = [f"{bad}aa" for bad in NOT_LOWER_CASE] + [
    "qaa\n", "qaa ", " qaa", "qa", "", "qaaa", "QAA", "qaA", "qaa-Qaaa",
]  # fmt: skip
BAD_SCRIPT_CODE = (
    [f"{bad}aaa" for bad in NOT_A_CAPITAL]
    + [f"Q{bad}aa" for bad in NOT_LOWER_CASE]
    + ["Qaaa\n", "Qaaa ", " Qaaa", "Qaa", "", "Qaaaa", "QAAA", "qaaa", "QaaA"]
)
NOT_TEXT: list[Any] = [None, 1, b"XA", ["X", "A"]]

BAD_NAMES = ["", " ", "\t\n ", " ", "  ", "T" * 201, "TEST \x00 name"]


def _country(actor: AuthenticationContext, number: int = 0, **values: Any) -> uuid.UUID:
    alpha2, alpha3, name_en = COUNTRIES[number]
    return services.create_country(
        actor=actor, **{"alpha2": alpha2, "alpha3": alpha3, "name_en": name_en, **values}
    )


def _language(actor: AuthenticationContext, number: int = 0, **values: Any) -> uuid.UUID:
    code, script_code, name_en = LANGUAGES[number]
    return services.create_language(
        actor=actor, **{"code": code, "script_code": script_code, "name_en": name_en, **values}
    )


# Each kind of record with its operations, so that a rule the two share is
# tested for both.
KINDS = [
    pytest.param(
        Country,
        "registry.country",
        _country,
        services.rename_country,
        services.deactivate_country,
        services.reactivate_country,
        id="country",
    ),
    pytest.param(
        Language,
        "registry.language",
        _language,
        services.rename_language,
        services.deactivate_language,
        services.reactivate_language,
        id="language",
    ),
]
KIND = ("model", "target_type", "create", "rename", "deactivate", "reactivate")


# --- Creating a country -------------------------------------------------------


@pytest.mark.parametrize(("alpha2", "alpha3", "name_en"), COUNTRIES)
def test_a_country_is_created_active_with_what_was_entered(
    administrator: AuthenticationContext, alpha2: str, alpha3: str, name_en: str
) -> None:
    public_id = services.create_country(
        actor=administrator, alpha2=alpha2, alpha3=alpha3, name_en=name_en
    )

    country = Country.objects.get()
    assert (country.alpha2, country.alpha3, country.name_en, country.is_active) == (
        alpha2,
        alpha3,
        name_en,
        True,
    )
    assert country.public_id == public_id
    assert isinstance(public_id, uuid.UUID) and public_id.version == 4
    assert events() == [("created", "registry.country", public_id, administrator.user.pk)]
    assert changes() == []


@pytest.mark.parametrize("alpha2", BAD_ALPHA2 + NOT_TEXT)
def test_a_country_with_an_alpha2_code_of_the_wrong_form_is_refused(
    administrator: AuthenticationContext, alpha2: Any
) -> None:
    with pytest.raises(InvalidEntryError):
        _country(administrator, alpha2=alpha2)

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


@pytest.mark.parametrize("alpha3", BAD_ALPHA3 + NOT_TEXT)
def test_a_country_with_an_alpha3_code_of_the_wrong_form_is_refused(
    administrator: AuthenticationContext, alpha3: Any
) -> None:
    with pytest.raises(InvalidEntryError):
        _country(administrator, alpha3=alpha3)

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


def test_a_code_is_stored_exactly_as_entered_and_never_converted(
    administrator: AuthenticationContext,
) -> None:
    """A code in the wrong case is refused, not put into the right one."""
    with pytest.raises(InvalidEntryError):
        _country(administrator, alpha2="xa", alpha3="xaa")
    with pytest.raises(InvalidEntryError):
        _language(administrator, code="QAA", script_code="QAAA")

    assert not Country.objects.exists() and not Language.objects.exists()


def test_a_code_needs_only_the_right_form_and_no_assignment(
    administrator: AuthenticationContext,
) -> None:
    """No list of assigned codes is consulted: any code of the right form is entered."""
    _country(administrator, alpha2="ZZ", alpha3="ZZZ")
    _language(administrator, code="qtz", script_code="Qabx")

    assert Country.objects.count() == 1 and Language.objects.count() == 1


@pytest.mark.parametrize(
    ("alpha2", "alpha3"), [("XA", "XBB"), ("XB", "XAA"), ("XA", "XAA")], ids=str
)
def test_a_country_whose_code_is_in_use_is_refused(
    administrator: AuthenticationContext, alpha2: str, alpha3: str
) -> None:
    _country(administrator)
    before = stored()

    with pytest.raises(DuplicateCodeError):
        _country(administrator, alpha2=alpha2, alpha3=alpha3, name_en="TEST Other")

    assert stored() == before


def test_a_code_of_a_deactivated_country_is_still_in_use(
    administrator: AuthenticationContext,
) -> None:
    services.deactivate_country(actor=administrator, public_id=_country(administrator))

    with pytest.raises(DuplicateCodeError):
        _country(administrator)

    assert Country.objects.count() == 1


def test_two_countries_may_have_the_same_name(administrator: AuthenticationContext) -> None:
    _country(administrator, 0, name_en="TEST Same name")
    _country(administrator, 1, name_en="TEST Same name")

    assert list(Country.objects.values_list("name_en", flat=True)) == ["TEST Same name"] * 2


# --- Creating a language ------------------------------------------------------


@pytest.mark.parametrize(("code", "script_code", "name_en"), LANGUAGES)
def test_a_language_is_created_active_with_what_was_entered(
    administrator: AuthenticationContext, code: str, script_code: str, name_en: str
) -> None:
    public_id = services.create_language(
        actor=administrator, code=code, script_code=script_code, name_en=name_en
    )

    language = Language.objects.get()
    assert (language.code, language.script_code, language.name_en, language.is_active) == (
        code,
        script_code,
        name_en,
        True,
    )
    assert language.public_id == public_id
    assert isinstance(public_id, uuid.UUID) and public_id.version == 4
    assert events() == [("created", "registry.language", public_id, administrator.user.pk)]
    assert changes() == []


@pytest.mark.parametrize("code", BAD_LANGUAGE_CODE + NOT_TEXT)
def test_a_language_with_a_language_code_of_the_wrong_form_is_refused(
    administrator: AuthenticationContext, code: Any
) -> None:
    """A two-letter code, and a language and a script joined in one value, are among them."""
    with pytest.raises(InvalidEntryError):
        _language(administrator, code=code)

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


@pytest.mark.parametrize("script_code", BAD_SCRIPT_CODE + NOT_TEXT)
def test_a_language_with_a_script_code_of_the_wrong_form_is_refused(
    administrator: AuthenticationContext, script_code: Any
) -> None:
    with pytest.raises(InvalidEntryError):
        _language(administrator, script_code=script_code)

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


def test_a_language_whose_pair_of_codes_is_in_use_is_refused(
    administrator: AuthenticationContext,
) -> None:
    _language(administrator)
    before = stored()

    with pytest.raises(DuplicateCodeError):
        _language(administrator, name_en="TEST Other")

    assert stored() == before


def test_a_language_is_unique_by_the_pair_and_not_by_either_code(
    administrator: AuthenticationContext,
) -> None:
    for number in range(len(LANGUAGES)):
        _language(administrator, number)

    assert list(Language.objects.order_by("id").values_list("code", "script_code")) == [
        (code, script_code) for code, script_code, _ in LANGUAGES
    ]


def test_two_languages_may_have_the_same_name(administrator: AuthenticationContext) -> None:
    _language(administrator, 0, name_en="TEST Same name")
    _language(administrator, 1, name_en="TEST Same name")

    assert Language.objects.filter(name_en="TEST Same name").count() == 2


# --- The English name, for both -----------------------------------------------


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("name_en", BAD_NAMES + [None, 1, b"TEST"])
def test_a_record_with_no_usable_name_is_not_created(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
    name_en: Any,
) -> None:
    with pytest.raises(InvalidEntryError):
        create(administrator, name_en=name_en)

    assert stored() == {"countries": [], "languages": [], "events": [], "changes": []}


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize(
    ("entered", "kept"),
    [
        ("  TEST Name  ", "TEST Name"),
        ("\tTEST Name\n", "TEST Name"),
        (" TEST Name ", "TEST Name"),
        ("TEST  inner   spaces", "TEST  inner   spaces"),
        ("T" * 200, "T" * 200),
        (" " * 50 + "T" * 200 + " " * 50, "T" * 200),
    ],
    ids=["spaces", "tab-and-line-break", "other-whitespace", "inner", "longest", "longest-padded"],
)
def test_a_name_is_stored_without_the_whitespace_around_it_and_otherwise_as_entered(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
    entered: str,
    kept: str,
) -> None:
    create(administrator, name_en=entered)

    assert model.objects.get().name_en == kept


@pytest.mark.parametrize(KIND, KINDS)
def test_a_rename_stores_the_name_and_records_the_old_and_the_new_one(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator, name_en="TEST Old name")

    rename(actor=administrator, public_id=public_id, name_en="TEST New name")

    assert model.objects.get().name_en == "TEST New name"
    assert events() == [
        ("created", target_type, public_id, administrator.user.pk),
        ("updated", target_type, public_id, administrator.user.pk),
    ]
    event = AuditEvent.objects.get(action="updated")
    assert changes() == [(event.pk, "name_en", "TEST Old name", "TEST New name")]


@pytest.mark.parametrize(KIND, KINDS)
def test_a_rename_records_the_name_as_it_is_stored_and_not_as_it_was_typed(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator, name_en="  TEST Old name ")

    rename(actor=administrator, public_id=public_id, name_en="\tTEST New name\n ")

    stored_name = model.objects.get().name_en
    assert stored_name == "TEST New name"
    assert [(old, new) for _, _, old, new in changes()] == [("TEST Old name", stored_name)]


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("name_en", ["TEST Name", " TEST Name", "TEST Name\n", " TEST Name\t"])
def test_a_rename_to_the_stored_name_is_refused_also_when_only_whitespace_differs(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
    name_en: str,
) -> None:
    public_id = create(administrator, name_en="TEST Name")
    before = stored()

    with pytest.raises(NoChangeError):
        rename(actor=administrator, public_id=public_id, name_en=name_en)

    assert stored() == before


@pytest.mark.parametrize(KIND, KINDS)
def test_a_rename_that_differs_only_in_case_or_inner_spacing_is_a_change(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    """A name is compared as stored: nothing is folded or collapsed to find it equal."""
    public_id = create(administrator, name_en="TEST Name")

    rename(actor=administrator, public_id=public_id, name_en="TEST name")
    rename(actor=administrator, public_id=public_id, name_en="TEST  name")

    assert model.objects.get().name_en == "TEST  name"
    assert [(old, new) for _, _, old, new in changes()] == [
        ("TEST Name", "TEST name"),
        ("TEST name", "TEST  name"),
    ]


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("name_en", BAD_NAMES)
def test_a_rename_to_no_usable_name_is_refused(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
    name_en: str,
) -> None:
    public_id = create(administrator)
    before = stored()

    with pytest.raises(InvalidEntryError):
        rename(actor=administrator, public_id=public_id, name_en=name_en)

    assert stored() == before


@pytest.mark.parametrize(KIND, KINDS)
def test_the_longest_name_can_be_recorded_as_an_old_and_as_a_new_value(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    """A name is never too long for the audit record to hold it."""
    public_id = create(administrator, name_en="A" * 200)

    rename(actor=administrator, public_id=public_id, name_en="B" * 200)

    assert [(old, new) for _, _, old, new in changes()] == [("A" * 200, "B" * 200)]


@pytest.mark.parametrize(KIND, KINDS)
def test_a_rename_changes_nothing_but_the_name(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    before = model.objects.values().get()

    rename(actor=administrator, public_id=public_id, name_en="TEST New name")

    assert model.objects.values().get() == {**before, "name_en": "TEST New name"}


# --- Deactivating and reactivating, for both ----------------------------------


@pytest.mark.parametrize(KIND, KINDS)
def test_a_deactivated_record_stays_and_can_be_reactivated(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    before = model.objects.values().get()

    deactivate(actor=administrator, public_id=public_id)

    assert model.objects.values().get() == {**before, "is_active": False}

    reactivate(actor=administrator, public_id=public_id)

    assert model.objects.values().get() == before
    assert events() == [
        ("created", target_type, public_id, administrator.user.pk),
        ("deactivated", target_type, public_id, administrator.user.pk),
        ("reactivated", target_type, public_id, administrator.user.pk),
    ]
    assert changes() == []


def test_a_deactivated_country_and_language_stay_readable(
    administrator: AuthenticationContext,
) -> None:
    country = _country(administrator)
    language = _language(administrator)

    services.deactivate_country(actor=administrator, public_id=country)
    services.deactivate_language(actor=administrator, public_id=language)

    assert [(entry.public_id, entry.is_active) for entry in selectors.countries(administrator)] == [
        (country, False)
    ]
    assert [(entry.public_id, entry.is_active) for entry in selectors.languages(administrator)] == [
        (language, False)
    ]


@pytest.mark.parametrize(KIND, KINDS)
def test_deactivating_a_deactivated_record_is_refused(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    deactivate(actor=administrator, public_id=public_id)
    before = stored()

    with pytest.raises(NoChangeError):
        deactivate(actor=administrator, public_id=public_id)

    assert stored() == before


@pytest.mark.parametrize(KIND, KINDS)
def test_reactivating_an_active_record_is_refused(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    before = stored()

    with pytest.raises(NoChangeError):
        reactivate(actor=administrator, public_id=public_id)

    assert stored() == before


@pytest.mark.parametrize(KIND, KINDS)
def test_a_deactivated_record_can_be_renamed(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    deactivate(actor=administrator, public_id=public_id)

    rename(actor=administrator, public_id=public_id, name_en="TEST New name")

    assert model.objects.values_list("name_en", "is_active").get() == ("TEST New name", False)


# --- Naming the record --------------------------------------------------------


@pytest.mark.parametrize(KIND, KINDS)
@pytest.mark.parametrize("operation", ["rename", "deactivate", "reactivate"])
@pytest.mark.parametrize("public_id", [UNKNOWN, "not-a-uuid", 1, None])
def test_a_change_to_a_record_that_does_not_exist_is_refused(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
    operation: str,
    public_id: Any,
) -> None:
    create(administrator)
    before = stored()
    values = {"name_en": "TEST New name"} if operation == "rename" else {}
    change = {"rename": rename, "deactivate": deactivate, "reactivate": reactivate}[operation]

    with pytest.raises(RecordNotFoundError):
        change(actor=administrator, public_id=public_id, **values)

    assert stored() == before


def test_a_record_is_not_named_by_its_internal_key(administrator: AuthenticationContext) -> None:
    _country(administrator)
    key = Country.objects.get().pk

    with pytest.raises(RecordNotFoundError):
        services.deactivate_country(actor=administrator, public_id=key)  # type: ignore[arg-type]  # an internal key in place of the identifier is the case under test

    assert Country.objects.get().is_active


def test_a_country_is_not_changed_through_the_identifier_of_a_language(
    administrator: AuthenticationContext,
) -> None:
    country = _country(administrator)
    language = _language(administrator)

    with pytest.raises(RecordNotFoundError):
        services.deactivate_country(actor=administrator, public_id=language)
    with pytest.raises(RecordNotFoundError):
        services.deactivate_language(actor=administrator, public_id=country)

    assert Country.objects.get().is_active and Language.objects.get().is_active


# --- The same rules for every country (ADR-0018 testing requirement 10) -------


@pytest.mark.parametrize("number", range(len(COUNTRIES)))
def test_each_synthetic_country_lives_under_the_same_rules(
    administrator: AuthenticationContext, number: int
) -> None:
    identifiers = [_country(administrator, each) for each in range(len(COUNTRIES))]
    chosen = identifiers[number]
    others = [identifier for identifier in identifiers if identifier != chosen]
    others_before = list(Country.objects.filter(public_id__in=others).order_by("id").values())
    alpha2, alpha3, _ = COUNTRIES[number]

    with pytest.raises(DuplicateCodeError):
        _country(administrator, number)
    services.rename_country(actor=administrator, public_id=chosen, name_en="TEST Renamed")
    with pytest.raises(NoChangeError):
        services.rename_country(actor=administrator, public_id=chosen, name_en="TEST Renamed")
    services.deactivate_country(actor=administrator, public_id=chosen)
    with pytest.raises(NoChangeError):
        services.deactivate_country(actor=administrator, public_id=chosen)
    services.reactivate_country(actor=administrator, public_id=chosen)
    with pytest.raises(NoChangeError):
        services.reactivate_country(actor=administrator, public_id=chosen)

    country = Country.objects.get(public_id=chosen)
    assert (country.alpha2, country.alpha3, country.name_en, country.is_active) == (
        alpha2,
        alpha3,
        "TEST Renamed",
        True,
    )
    assert list(Country.objects.filter(public_id__in=others).order_by("id").values()) == (
        others_before
    )
    assert [action for action, _, target, _ in events() if target == chosen] == [
        "created",
        "updated",
        "deactivated",
        "reactivated",
    ]
    assert not [target for _, _, target, _ in events()[len(COUNTRIES) :] if target != chosen]


# --- What the audit record holds (ADR-0018 testing requirement 9) -------------


@pytest.mark.parametrize(KIND, KINDS)
def test_every_event_names_the_account_that_acted_the_record_and_the_request(
    administrator: AuthenticationContext,
    acting_as: Any,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    other = acting_as("administrator", second_factor=True)
    with correlation_scope() as first:
        public_id = create(administrator)
    with correlation_scope() as second:
        rename(actor=other, public_id=public_id, name_en="TEST New name")
    with correlation_scope() as third:
        deactivate(actor=administrator, public_id=public_id)
    with correlation_scope() as fourth:
        reactivate(actor=other, public_id=public_id)

    rows = list(
        AuditEvent.objects.order_by("id").values(
            "action", "target_type", "target_public_id", "actor_id", "correlation_id"
        )
    )
    assert rows == [
        {
            "action": action,
            "target_type": target_type,
            "target_public_id": public_id,
            "actor_id": actor.user.pk,
            "correlation_id": correlation_id,
        }
        for action, actor, correlation_id in [
            ("created", administrator, first),
            ("updated", other, second),
            ("deactivated", administrator, third),
            ("reactivated", other, fourth),
        ]
    ]
    assert len({first, second, third, fourth}) == 4


@pytest.mark.parametrize(KIND, KINDS)
def test_only_an_update_has_change_records_and_only_for_the_name(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator, name_en="TEST Old name")
    rename(actor=administrator, public_id=public_id, name_en="TEST New name")
    deactivate(actor=administrator, public_id=public_id)
    reactivate(actor=administrator, public_id=public_id)

    by_action = {
        event.action: list(event.changes.values_list("field", "old_value", "new_value"))
        for event in AuditEvent.objects.all()
    }
    assert by_action == {
        "created": [],
        "updated": [("name_en", "TEST Old name", "TEST New name")],
        "deactivated": [],
        "reactivated": [],
    }
    assert AuditEventChange.objects.count() == 1


@pytest.mark.parametrize(KIND, KINDS)
def test_an_event_holds_nothing_but_what_was_done_to_which_record_by_whom(
    administrator: AuthenticationContext,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    """No code, no email address, no session, no source address: ADR-0018 point 36."""
    with correlation_scope() as correlation_id:
        public_id = create(administrator, name_en="TEST Old name")
        rename(actor=administrator, public_id=public_id, name_en="TEST New name")
    record = model.objects.values().get()
    codes = {
        value
        for name, value in record.items()
        if name in {"alpha2", "alpha3", "code", "script_code"}
    }

    assert list(
        AuditEvent.objects.order_by("id").values(
            "action", "target_type", "target_public_id", "actor_id", "correlation_id"
        )
    ) == [
        {
            "action": action,
            "target_type": target_type,
            "target_public_id": public_id,
            "actor_id": administrator.user.pk,
            "correlation_id": correlation_id,
        }
        for action in ("created", "updated")
    ]
    # Every column of both tables, so that a column added later is seen here.
    assert {field.column for field in AuditEvent._meta.concrete_fields} == {
        "id",
        "action",
        "target_type",
        "target_public_id",
        "actor_id",
        "correlation_id",
        "created_at",
    }
    assert {field.column for field in AuditEventChange._meta.concrete_fields} == {
        "id",
        "event_id",
        "field",
        "old_value",
        "new_value",
    }
    written = " ".join(
        str(value)
        for row in [*AuditEvent.objects.values(), *AuditEventChange.objects.values()]
        for name, value in row.items()
        if name != "target_type"
    )
    assert administrator.user.email not in written
    assert not [code for code in codes if code in written.replace("TEST", "")]


# --- Logging ------------------------------------------------------------------


@pytest.mark.parametrize(KIND, KINDS)
def test_each_change_is_logged_with_the_identifier_and_no_value(
    administrator: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    with caplog.at_level(logging.INFO, logger="caipo.registry.services"):
        public_id = create(administrator, name_en="TEST Old name")
        rename(actor=administrator, public_id=public_id, name_en="TEST New name")
        deactivate(actor=administrator, public_id=public_id)
        reactivate(actor=administrator, public_id=public_id)

    records = [record for record in caplog.records if record.name == "caipo.registry.services"]
    assert [
        (record.__dict__["event"], record.__dict__["public_id"], record.__dict__["actor_id"])
        for record in records
    ] == [
        (f"{target_type}_{action}", str(public_id), administrator.user.pk)
        for action in ("created", "updated", "deactivated", "reactivated")
    ]
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in records)
    assert "TEST Old name" not in logged and "TEST New name" not in logged
    assert administrator.user.email not in logged


@pytest.mark.parametrize(KIND, KINDS)
def test_a_refused_change_is_not_logged_as_made(
    administrator: AuthenticationContext,
    caplog: pytest.LogCaptureFixture,
    model: Any,
    target_type: str,
    create: Create,
    rename: Change,
    deactivate: Change,
    reactivate: Change,
) -> None:
    public_id = create(administrator)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="caipo.registry.services"):
        with pytest.raises(NoChangeError):
            reactivate(actor=administrator, public_id=public_id)
        with pytest.raises(InvalidEntryError):
            rename(actor=administrator, public_id=public_id, name_en=" ")
        with pytest.raises(DuplicateCodeError):
            create(administrator)
        with pytest.raises(RecordNotFoundError):
            deactivate(actor=administrator, public_id=UNKNOWN)

    assert [record for record in caplog.records if record.name == "caipo.registry.services"] == []
