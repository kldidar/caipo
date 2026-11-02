"""The two classes of data of the demonstrator, and the rule that keeps them apart (ADR-0020).

A record is `demonstration` (synthetic, to show what the software does) or
`reference` (a real public source, document, or value). A demonstration
record belongs only to a synthetic country, and a reference record never
does. Which countries are synthetic is decided by the code alone: the codes
ISO 3166-1 leaves for user assignment. No named country is ever singled out.
"""

from string import ascii_uppercase

from django.db import models
from django.utils.translation import gettext_lazy as _


class DataClass(models.TextChoices):
    DEMONSTRATION = "demonstration", _("Demonstration data")
    REFERENCE = "reference", _("Reference data")


# The ISO 3166-1 alpha-2 codes left for user assignment: AA, QM to QZ, XA to
# XZ, and ZZ. Written as the second letters each first letter allows, so the
# rule names a range of codes and never a country.
_USER_ASSIGNED: dict[str, str] = {
    "A": "A",
    "Q": "MNOPQRSTUVWXYZ",
    "X": ascii_uppercase,
    "Z": "Z",
}
SYNTHETIC_ALPHA2_CODES: frozenset[str] = frozenset(
    first + second for first, seconds in _USER_ASSIGNED.items() for second in seconds
)


def is_synthetic_country(alpha2: str) -> bool:
    """Return whether a country code is one ISO 3166-1 leaves for user assignment."""
    return alpha2 in SYNTHETIC_ALPHA2_CODES


def country_fits(data_class: str, alpha2: str) -> bool:
    """Return whether a record of this data class may belong to a country with this code."""
    return is_synthetic_country(alpha2) == (data_class == DataClass.DEMONSTRATION)
