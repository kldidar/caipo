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
