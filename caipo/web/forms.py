from django import forms
from django.utils.translation import gettext_lazy as _

from caipo.accounts.selectors import Role


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
