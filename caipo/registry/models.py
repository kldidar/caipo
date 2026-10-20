"""Countries, languages, institutions, and the names of institutions: the reference
records that other records point at (ADR-0018, ADR-0019).

Mutable domain records, not provenance records and not append-only. Their
accountability comes from the audit record that the services write, not from
immutability. What never changes is a record's identity: the codes of a
country or a language, everything of an institution's name but its dates,
and every public identifier. Nothing here is deleted.

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


# The longest text of an institution's name (owner decision of 2026-10-20).
# A name's text is never written to the audit record, so the limit of an
# audited value does not bound it.
INSTITUTION_NAME_MAX_LENGTH = 500


class InstitutionKind(models.TextChoices):
    """What kind of body an institution is (ADR-0018 point 10). There are no others.

    There is no "other" kind. A body that fits none of these is not recorded
    under the nearest one: the list is extended first, by a change to
    docs/DATA_MODEL.md and a migration that widens the check.
    """

    MINISTRY = "ministry", _("Ministry")
    LEGISLATURE = "legislature", _("Legislature")
    REGULATOR = "regulator", _("Regulator")
    STATISTICAL_AGENCY = "statistical_agency", _("Statistical agency")
    INTERNATIONAL_ORGANISATION = "international_organisation", _("International organisation")
    UNIVERSITY = "university", _("University")
    MEDIA_OUTLET = "media_outlet", _("Media outlet")
    COMPANY = "company", _("Company")


class InstitutionNameKind(models.TextChoices):
    """What kind of name a name of an institution is (ADR-0018 point 9)."""

    OFFICIAL = "official", _("Official")
    TRANSLITERATION = "transliteration", _("Transliteration")
    ENGLISH_RENDERING = "english_rendering", _("English rendering")
    ABBREVIATION = "abbreviation", _("Abbreviation")


def _dates_in_order() -> models.Q:
    """Where both dates are known, the first day comes before the first day not covered."""
    return (
        models.Q(valid_from__isnull=True)
        | models.Q(valid_to__isnull=True)
        | models.Q(valid_from__lt=models.F("valid_to"))
    )


class Institution(models.Model):
    """A body that issues, implements, or publishes (ADR-0018 points 8, 10, 21, and 22).

    It has no active flag: its validity period says whether it exists. An
    unknown date is empty, and a date is a full calendar date. The period is
    half-open: valid-from is the first day, valid-to the first day no longer
    covered. A renamed body is the same institution and gets a new name; a
    successor is a different institution that took over from this one when
    it ended.

    Only the public identifier is set once. The kind, country, parent,
    dates, and successor can be changed, and every change is audited. A
    database trigger refuses an UPDATE of the public identifier, and every
    DELETE.
    """

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    kind = models.CharField(_("kind"), max_length=32, choices=InstitutionKind)
    # Empty for a body that belongs to no country, such as an international
    # organisation. PROTECT, and no record is ever deleted anyway.
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("country"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("parent institution"),
    )
    valid_from = models.DateField(_("valid from"), null=True, blank=True)
    valid_to = models.DateField(_("valid to"), null=True, blank=True)
    successor = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("successor"),
    )

    class Meta:
        verbose_name = _("institution")
        verbose_name_plural = _("institutions")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="registry_institution_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=InstitutionKind.values),
                name="registry_institution_kind_known",
            ),
            models.CheckConstraint(
                condition=_dates_in_order(), name="registry_institution_dates_in_order"
            ),
            models.CheckConstraint(
                condition=models.Q(parent__isnull=True) | ~models.Q(parent=models.F("id")),
                name="registry_institution_not_own_parent",
            ),
            models.CheckConstraint(
                condition=models.Q(successor__isnull=True) | ~models.Q(successor=models.F("id")),
                name="registry_institution_not_own_successor",
            ),
            models.CheckConstraint(
                condition=models.Q(successor__isnull=True) | models.Q(valid_to__isnull=False),
                name="registry_institution_successor_needs_valid_to",
            ),
        ]

    def __str__(self) -> str:
        return str(self.public_id)


class InstitutionName(models.Model):
    """One name of an institution, in a language and a script (ADR-0018 points 9, 19, and 20).

    A historical record: the institution, text, language, and kind never
    change after creation, and a body that is renamed gets a new name row.
    Only the two validity dates can be changed. The text is stored in
    Unicode Normalization Form C and is not case-folded or transliterated.

    A name entered by mistake is marked as entered in error. The mark is
    empty when the name is created, is set once, and is never cleared. A
    marked name stays, and is not shown as a name of the institution. A
    database trigger refuses an UPDATE of anything else, the clearing of the
    mark, and every DELETE.
    """

    public_id = models.UUIDField(_("public identifier"), default=uuid.uuid4, editable=False)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        related_name="names",
        verbose_name=_("institution"),
    )
    text = models.CharField(_("text"), max_length=INSTITUTION_NAME_MAX_LENGTH)
    language = models.ForeignKey(
        Language, on_delete=models.PROTECT, related_name="+", verbose_name=_("language")
    )
    kind = models.CharField(_("kind"), max_length=32, choices=InstitutionNameKind)
    valid_from = models.DateField(_("valid from"), null=True, blank=True)
    valid_to = models.DateField(_("valid to"), null=True, blank=True)
    entered_in_error = models.BooleanField(_("entered in error"), default=False)

    class Meta:
        verbose_name = _("institution name")
        verbose_name_plural = _("institution names")
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="registry_institutionname_public_id_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=InstitutionNameKind.values),
                name="registry_institutionname_kind_known",
            ),
            models.CheckConstraint(
                condition=_dates_in_order(), name="registry_institutionname_dates_in_order"
            ),
        ]

    def __str__(self) -> str:
        return str(self.public_id)
