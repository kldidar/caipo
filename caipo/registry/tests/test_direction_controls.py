"""Names that hold an invisible direction control are refused (diagnostic of 2026-10-20, L5).

The characters that embed, override, or isolate a direction of text, U+202A
to U+202E and U+2066 to U+2069, can make a name read differently from the
characters it holds. Every operation that takes a name refuses them, stores
nothing, and records nothing. Letters of every script, and the implicit
direction marks that reorder nothing around them, are accepted as entered.
"""

from collections.abc import Callable

import pytest

from caipo.accounts.selectors import AuthenticationContext
from caipo.registry import services
from caipo.registry.models import Country, InstitutionName, Language
from caipo.registry.services import DirectionControlError, InvalidEntryError, NewName
from caipo.registry.tests.helpers import institution, reference_records, stored_with_institutions

pytestmark = [pytest.mark.services, pytest.mark.django_db]

DIRECTION_CONTROLS = [
    "\u202a",  # LEFT-TO-RIGHT EMBEDDING
    "\u202b",  # RIGHT-TO-LEFT EMBEDDING
    "\u202c",  # POP DIRECTIONAL FORMATTING
    "\u202d",  # LEFT-TO-RIGHT OVERRIDE
    "\u202e",  # RIGHT-TO-LEFT OVERRIDE
    "\u2066",  # LEFT-TO-RIGHT ISOLATE
    "\u2067",  # RIGHT-TO-LEFT ISOLATE
    "\u2068",  # FIRST STRONG ISOLATE
    "\u2069",  # POP DIRECTIONAL ISOLATE
]
# Synthetic names in the scripts and letters the registry is used with,
# and the three implicit marks, which are allowed.
ACCEPTED = [
    "TEST Döwlet statistika komiteti",
    "TEST Ýörite ňňň şçž",
    "TEST Oʻzbekiston gʻ",
    "TEST Государственный комитет Ўзбекистон қ ғ ҳ",
    "TEST \u200e mark \u200f mark \u061c mark",
]

type Operation = Callable[[AuthenticationContext, str], object]


class Records:
    def __init__(self, actor: AuthenticationContext) -> None:
        countries, languages = reference_records(actor)
        self.country, self.language = countries[0], languages[0]
        self.institution = institution(actor, self.language)


@pytest.fixture
def records(administrator: AuthenticationContext) -> Records:
    return Records(administrator)


def _operations(records: Records) -> dict[str, Operation]:
    """Every operation that takes a name, given the name to enter."""
    codes = iter(["XC", "XD", "XE", "XF", "XG", "XH", "XI", "XJ", "XK", "XL", "XM", "XN"])
    scripts = iter(["Qaac", "Qaad", "Qaae", "Qaaf", "Qaag", "Qaah", "Qaai", "Qaaj", "Qaak"])

    def create_country(actor: AuthenticationContext, text: str) -> object:
        code = next(codes)
        return services.create_country(actor=actor, alpha2=code, alpha3=code + "A", name_en=text)

    def create_language(actor: AuthenticationContext, text: str) -> object:
        return services.create_language(
            actor=actor, code="qac", script_code=next(scripts), name_en=text
        )

    return {
        "create a country": create_country,
        "rename a country": lambda actor, text: services.rename_country(
            actor=actor, public_id=records.country, name_en=text
        ),
        "create a language": create_language,
        "rename a language": lambda actor, text: services.rename_language(
            actor=actor, public_id=records.language, name_en=text
        ),
        "create an institution": lambda actor, text: institution(actor, records.language, text),
        "add a name": lambda actor, text: services.add_institution_name(
            actor=actor,
            institution=records.institution,
            name=NewName(text=text, language=records.language, kind="english_rendering"),
        ),
    }


OPERATIONS = [
    "create a country",
    "rename a country",
    "create a language",
    "rename a language",
    "create an institution",
    "add a name",
]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("control", DIRECTION_CONTROLS)
@pytest.mark.parametrize("place", ["start", "inside", "end"])
def test_a_name_with_a_direction_control_is_refused_and_nothing_is_stored(
    administrator: AuthenticationContext,
    records: Records,
    operation: str,
    control: str,
    place: str,
) -> None:
    text = {
        "start": f"{control}TEST Name",
        "inside": f"TEST {control}Name",
        "end": f"TEST Name{control}",
    }[place]
    before = stored_with_institutions()

    with pytest.raises(DirectionControlError):
        _operations(records)[operation](administrator, text)

    assert stored_with_institutions() == before


def test_a_direction_control_is_a_kind_of_invalid_entry() -> None:
    """A caller that answers every invalid entry alike still answers this one."""
    assert issubclass(DirectionControlError, InvalidEntryError)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("text", ACCEPTED)
def test_letters_of_every_script_and_the_implicit_marks_are_accepted_as_entered(
    administrator: AuthenticationContext, records: Records, operation: str, text: str
) -> None:
    _operations(records)[operation](administrator, text)

    assert (
        Country.objects.filter(name_en=text).exists()
        or Language.objects.filter(name_en=text).exists()
        or InstitutionName.objects.filter(text=text).exists()
    )


def test_a_direction_control_is_refused_after_normalisation(
    administrator: AuthenticationContext, records: Records
) -> None:
    """NFC composes letters and leaves the controls as they are, so it cannot hide one."""
    with pytest.raises(DirectionControlError):
        services.add_institution_name(
            actor=administrator,
            institution=records.institution,
            name=NewName(
                text="TEST Do\u0308wlet\u202e", language=records.language, kind="official"
            ),
        )
