from django import forms
from django.utils.translation import gettext_lazy as _


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


class EnrollmentApprovalForm(forms.Form):
    """The explicit confirmation without which an enrolment request is not approved."""

    confirmed = forms.BooleanField(
        label=_("I asked this person for their request number, and it is this one."),
        required=True,
    )

    def clean_confirmed(self) -> bool:
        # Only what a ticked box sends counts. Django would also take "0" or
        # any other non-empty text as a tick.
        if self.data.get("confirmed") != "on":
            raise forms.ValidationError(_("Tick the confirmation."))
        return True
