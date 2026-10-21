import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Final

from django import forms
from django.utils.translation import gettext_lazy as _

from caipo.accounts.selectors import Role
from caipo.registry.selectors import InstitutionKind, InstitutionNameKind

# The options of a field that refers to a registry record: its public
# identifier, and what the person choosing is shown.
type Options = Sequence[tuple[str, str]]


class SignInForm(forms.Form):
    """The fields of the sign-in page. It checks shape only; it authenticates nothing."""

    email = forms.EmailField(
        label=_("Email address"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label=_("Password"),
        # Bounded, so that hashing a submitted password has a bounded cost.
        max_length=1024,
        strip=False,
        # Never rendered back into the page.
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}, render_value=False),
    )


def _password_field() -> forms.CharField:
    return forms.CharField(
        label=_("Password"),
        max_length=1024,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}, render_value=False),
    )


def _code_field() -> forms.CharField:
    return forms.CharField(
        label=_("Six-digit code"),
        min_length=6,
        max_length=6,
        # Never rendered back into the page.
        widget=forms.PasswordInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}, render_value=False
        ),
    )


class SecondFactorCodeForm(forms.Form):
    """A code from the authenticator application. Shape only; it verifies nothing."""

    code = _code_field()


class PasswordConfirmationForm(forms.Form):
    """The current password, asked for again before a second factor is changed."""

    password = _password_field()


class DisableSecondFactorForm(forms.Form):
    """Both proofs, asked for again before a second factor is removed or replaced."""

    password = _password_field()
    code = _code_field()


class _ExplicitConfirmationForm(forms.Form):
    """A form with a `confirmed` box that must be ticked. Each one says what the tick confirms."""

    def clean_confirmed(self) -> bool:
        # Only what a ticked box sends counts. Django would also take "0" or
        # any other non-empty text as a tick.
        if self.data.get("confirmed") != "on":
            raise forms.ValidationError(_("Tick the confirmation."))
        return True


class EnrollmentApprovalForm(_ExplicitConfirmationForm):
    """The explicit confirmation without which an enrolment request is not approved."""

    confirmed = forms.BooleanField(
        label=_("I asked this person for their request number, and it is this one."),
        required=True,
    )


class RecoveryAuthorizationForm(_ExplicitConfirmationForm):
    """The explicit confirmation without which a recovery request is not authorised.

    A tick and nothing else: there is no field for how the person was
    identified, because nothing about that is stored (ADR-0017 point 33).
    """

    confirmed = forms.BooleanField(
        label=_(
            "I identified this person by a means other than this site, and they gave me"
            " this request number."
        ),
        required=True,
    )


class MarkEnteredInErrorForm(_ExplicitConfirmationForm):
    """The explicit confirmation without which a name is not marked as entered in error.

    The mark is never cleared (ADR-0018 point 19), so a single click is not
    enough to set it.
    """

    confirmed = forms.BooleanField(
        label=_(
            "I have checked that this name was entered by mistake. I understand that the mark"
            " cannot be undone."
        ),
        required=True,
    )


class AccountCreationForm(forms.Form):
    """Who a new account is for and which one role it starts with. Shape only.

    There is no password field: the Administrator who creates an account
    never chooses or sees its password.
    """

    email = forms.EmailField(
        label=_("Email address"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "off"}),
    )
    role = forms.ChoiceField(label=_("Role"), choices=Role.choices)


class _NewPasswordForm(forms.Form):
    """A code from a message and the password its holder chooses, typed twice."""

    field_order = ("token", "password", "password_again")

    password = forms.CharField(
        label=_("New password"),
        max_length=1024,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )
    password_again = forms.CharField(
        label=_("New password again"),
        max_length=1024,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        if cleaned.get("password") != cleaned.get("password_again"):
            raise forms.ValidationError(_("The two passwords are not the same."))
        return cleaned


def _token_field() -> forms.CharField:
    return forms.CharField(
        # A token is 43 characters. Bounded, so that hashing what was
        # submitted has a bounded cost.
        max_length=128,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )


class ActivationForm(_NewPasswordForm):
    """The code from the verification message and the password its owner chooses. Shape only."""

    token = _token_field()
    token.label = _("Activation code")


class PasswordResetRequestForm(forms.Form):
    """The email address a reset message is asked for. Shape only; it looks nothing up."""

    email = forms.EmailField(
        label=_("Email address"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )


class PasswordResetForm(_NewPasswordForm):
    """The code from the reset message and the new password its owner chooses. Shape only."""

    token = _token_field()
    token.label = _("Reset code")

    @classmethod
    def carrying(cls, token: str) -> PasswordResetForm:
        """Return an empty form that carries a token out of sight, in a hidden field.

        For the one case in which a token is kept across a response: the
        service found it good and refused the password. The token is then
        sent again in the body of the next POST and is nowhere in the visible
        page.
        """
        form = cls(initial={"token": token})
        form.fields["token"].widget = forms.HiddenInput()
        return form


def _registry_code_field() -> forms.CharField:
    return forms.CharField(
        # Far longer than any code, and bounded. Nothing is trimmed: a code is
        # accepted exactly as typed or not at all, and the service decides.
        max_length=16,
        strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )


def _registry_name_field() -> forms.CharField:
    return forms.CharField(
        label=_("English name"),
        # Longer than a name may be, and bounded. The service removes
        # surrounding whitespace and decides what is too long.
        max_length=1024,
        strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )


class CountryCreationForm(forms.Form):
    """The two codes and the English name of a new country. Shape only; it validates no code."""

    alpha2 = _registry_code_field()
    alpha2.label = _("Alpha-2 code")
    alpha3 = _registry_code_field()
    alpha3.label = _("Alpha-3 code")
    name_en = _registry_name_field()


class LanguageCreationForm(forms.Form):
    """The two codes and the English name of a new language. Shape only; it validates no code."""

    code = _registry_code_field()
    code.label = _("Language code")
    script_code = _registry_code_field()
    script_code.label = _("Script code")
    name_en = _registry_name_field()


class RegistryNameForm(forms.Form):
    """A new English name for a country or a language. Shape only."""

    name_en = _registry_name_field()


# YYYY-MM-DD in ASCII digits, every part padded with zeros. A Python range of
# ASCII digits matches those ten characters and no other digit.
_FULL_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class FullDateField(forms.DateField):
    """A date given as YYYY-MM-DD and in no other form, or nothing.

    Django's own parsing goes through `strptime`, which also takes digits of
    other scripts and parts without their leading zeros: `2020-1-1` and a
    year in full-width digits both become dates. Here the text is matched
    whole, as sent, before it is read as a date (diagnostic of 2026-10-20,
    L6).
    """

    def to_python(self, value: Any) -> date | None:
        if value in self.empty_values:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str) or _FULL_DATE.fullmatch(value) is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid") from None


def _registry_date_field() -> FullDateField:
    return FullDateField(
        required=False,
        # A full calendar date, or nothing. A date known only to the year or
        # the month is left empty (ADR-0018 point 21).
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )


def _registry_reference_field(*, required: bool = False) -> forms.UUIDField:
    # Shape only: that the record exists, and may be referred to, is the
    # service's to decide. The options are given to the form.
    return forms.UUIDField(required=required, widget=forms.Select())


def _offer(field: forms.Field, options: Options, *, empty: bool) -> None:
    nothing: list[tuple[str, Any]] = [("", _("None"))] if empty else []
    field.widget.choices = nothing + list(options)


class InstitutionForm(forms.Form):
    """The kind, country, parent, successor, and validity dates of an institution. Shape only."""

    kind = forms.ChoiceField(label=_("Kind"), choices=InstitutionKind.choices)
    country = _registry_reference_field()
    country.label = _("Country")
    parent = _registry_reference_field()
    parent.label = _("Parent institution")
    successor = _registry_reference_field()
    successor.label = _("Successor")
    valid_from = _registry_date_field()
    valid_from.label = _("Valid from")
    valid_to = _registry_date_field()
    valid_to.label = _("Valid to")

    def __init__(
        self, *args: Any, countries: Options = (), institutions: Options = (), **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        _offer(self.fields["country"], countries, empty=True)
        _offer(self.fields["parent"], institutions, empty=True)
        _offer(self.fields["successor"], institutions, empty=True)


class InstitutionNameForm(forms.Form):
    """A name of an institution: its text, language, kind, and validity dates. Shape only."""

    text = forms.CharField(
        label=_("Name"),
        # Longer than a name may be, and bounded. The service removes
        # surrounding whitespace and decides what is too long.
        max_length=2048,
        strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    language = _registry_reference_field(required=True)
    language.label = _("Language")
    kind = forms.ChoiceField(label=_("Kind of name"), choices=InstitutionNameKind.choices)
    valid_from = _registry_date_field()
    valid_from.label = _("Valid from")
    valid_to = _registry_date_field()
    valid_to.label = _("Valid to")

    def __init__(self, *args: Any, languages: Options = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _offer(self.fields["language"], languages, empty=False)


class InstitutionNameDatesForm(forms.Form):
    """New validity dates for a name of an institution. Shape only."""

    valid_from = _registry_date_field()
    valid_from.label = _("Valid from")
    valid_to = _registry_date_field()
    valid_to.label = _("Valid to")
