"""What the demonstrator's services refuse, and the checks they share (ADR-0020).

Knows no domain record: only text, addresses, and the three refusals that
the services of `sources` and `policies` raise.
"""

import re
import unicodedata

from django.utils.translation import gettext as _

# Characters that change the direction of the text around them. A title that
# holds one can be shown in an order that is not the order it was typed.
_DIRECTION_CONTROLS = re.compile("[‪-‮⁦-⁩]")
_WEB_ADDRESS = re.compile(r"^https?://\S+$")


class InvalidEntryError(ValueError):
    """A value given to a service is not acceptable. Nothing was stored."""


class RecordNotFoundError(LookupError):
    """A record named by its public identifier does not exist. Nothing was stored."""


class DataClassError(ValueError):
    """Records of different data classes, or a record and a country, would be mixed (ADR-0020)."""


def clean_text(value: str, *, field: str, max_length: int, required: bool = True) -> str:
    """Return the text in Unicode NFC with surrounding whitespace removed.

    Raises InvalidEntryError if it is required and empty, too long, or holds
    a direction control. Nothing else in it is changed.
    """
    text = unicodedata.normalize("NFC", value).strip()
    if required and not text:
        raise InvalidEntryError(_("The %(field)s is required.") % {"field": field})
    if len(text) > max_length:
        raise InvalidEntryError(
            _("The %(field)s is at most %(limit)d characters.")
            % {"field": field, "limit": max_length}
        )
    if _DIRECTION_CONTROLS.search(text):
        raise InvalidEntryError(
            _("The %(field)s holds a direction control character.") % {"field": field}
        )
    return text


def clean_address(value: str, *, field: str, max_length: int, required: bool = True) -> str:
    """Return a web address as given, without surrounding whitespace.

    Raises InvalidEntryError if it is required and empty, too long, or not an
    http or https address. The address is recorded, never fetched.
    """
    address = value.strip()
    if not address and not required:
        return ""
    if not address:
        raise InvalidEntryError(_("The %(field)s is required.") % {"field": field})
    if len(address) > max_length or not _WEB_ADDRESS.match(address):
        raise InvalidEntryError(_("The %(field)s is an http or https address.") % {"field": field})
    return address
