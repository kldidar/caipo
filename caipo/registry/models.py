"""Countries and languages: the reference records that other records point at (ADR-0018).

Mutable domain records, not provenance records and not append-only. Their
accountability comes from the audit record that the services write, not from
immutability. What never changes is a record's identity: its codes and its
public identifier. Nothing here is deleted.

No record refers to a user. Who created or changed one is what the audit
record says, and it is said in one place.
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

# The forms of the codes, as PostgreSQL regular expressions. Form only: no
# list of assigned codes is held (ADR-0018 point 6, ADR-0019 points 29 to 31).
#
# Each letter is written out. A range such as [A-Z] is read under the
# collation of the column, and under some collations it takes in letters
# that are not the twenty-six meant. A list of characters is the same list
# under every collation. In PostgreSQL `$` matches only at the end of the
# value, so a value that ends in a line break is refused.
#
# The code columns have no width of their own, and the check alone decides
# how long a code is. PostgreSQL does not refuse a value that is too long for
# a column of limited width when what is too much is spaces: it removes them
# and stores the rest. A code followed by a space would then be stored as
# that code and not refused.
_UPPER = "[ABCDEFGHIJKLMNOPQRSTUVWXYZ]"
_LOWER = "[abcdefghijklmnopqrstuvwxyz]"
COUNTRY_ALPHA2_PATTERN = f"^{_UPPER}{{2}}$"
COUNTRY_ALPHA3_PATTERN = f"^{_UPPER}{{3}}$"
LANGUAGE_CODE_PATTERN = f"^{_LOWER}{{3}}$"
LANGUAGE_SCRIPT_CODE_PATTERN = f"^{_UPPER}{_LOWER}{{3}}$"

# The longest English name. It is also the longest value a change record of
# the audit record holds, so a name is never too long to be audited.
NAME_MAX_LENGTH = 200


class Country(models.Model):
    """A country the system knows, under its two ISO 3166 codes (ADR-0018 point 6).

    The codes are checked for form only and are each unique. The codes and
    the public identifier are set once: no service changes them, and a
    database trigger refuses an UPDATE that would, and every DELETE. A
    country that is no longer to be referred to is deactivated, and stays.
    """

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    alpha2 = models.CharField(_("alpha-2 code"), max_length=None)
    alpha3 = models.CharField(_("alpha-3 code"), max_length=None)
    name_en = models.CharField(_("English name"), max_length=NAME_MAX_LENGTH)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("country")
        verbose_name_plural = _("countries")
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="registry_country_public_id_unique"),
            models.UniqueConstraint(fields=["alpha2"], name="registry_country_alpha2_unique"),
            models.UniqueConstraint(fields=["alpha3"], name="registry_country_alpha3_unique"),
            models.CheckConstraint(
                condition=models.Q(alpha2__regex=COUNTRY_ALPHA2_PATTERN),
                name="registry_country_alpha2_form",
            ),
            models.CheckConstraint(
                condition=models.Q(alpha3__regex=COUNTRY_ALPHA3_PATTERN),
                name="registry_country_alpha3_form",
            ),
        ]

    def __str__(self) -> str:
        return self.alpha2


class Language(models.Model):
    """A language in a script (ADR-0018 point 7, ADR-0019 points 29 to 32).

    The same language in two scripts is two records. The language code has
    the form of an ISO 639-3 code and the script code that of an ISO 15924
    code; both are checked for form only and are unique as a pair. The codes
    and the public identifier are set once: no service changes them, and a
    database trigger refuses an UPDATE that would, and every DELETE. A
    language that is no longer to be referred to is deactivated, and stays.
    """

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    code = models.CharField(_("language code"), max_length=None)
    script_code = models.CharField(_("script code"), max_length=None)
    name_en = models.CharField(_("English name"), max_length=NAME_MAX_LENGTH)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("language")
        verbose_name_plural = _("languages")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="registry_language_public_id_unique"
            ),
            models.UniqueConstraint(
                fields=["code", "script_code"], name="registry_language_codes_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=LANGUAGE_CODE_PATTERN),
                name="registry_language_code_form",
            ),
            models.CheckConstraint(
                condition=models.Q(script_code__regex=LANGUAGE_SCRIPT_CODE_PATTERN),
                name="registry_language_script_code_form",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code}-{self.script_code}"
