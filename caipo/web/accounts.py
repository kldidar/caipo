"""Pages on which an Administrator creates accounts (ADR-0015).

These views handle the request and nothing else. Who may create an account,
which roles exist, and what is recorded are decided by `caipo.accounts`. A
change is made by POST with a CSRF token. The acting Administrator comes from
the session; the form supplies an email address and a role and nothing else,
and never a password.

Disabling and enabling accounts have no page yet: they are service operations.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from caipo.accounts import selectors, services
from caipo.accounts.selectors import AuthenticationContext, Permission, Role
from caipo.accounts.services import AccountChangeError
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.activation import activation_url
from caipo.web.authentication import source
from caipo.web.forms import AccountCreationForm

INVALID_MESSAGE = _("Give an email address and choose one of the roles.")
NOT_SENT_MESSAGE = _(
    "The account exists, but its verification message could not be sent. Send it again below."
)
NOT_PENDING_MESSAGE = _("That account does not await verification.")
CREATED_QUERY = "created"
SENT_QUERY = "sent"


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _page(
    request: HttpRequest,
    actor: AuthenticationContext,
    *,
    form: AccountCreationForm | None = None,
    error: Promise | str | None = None,
    status: int = 200,
) -> HttpResponse:
    context = {
        "form": form or AccountCreationForm(),
        "error": error,
        "created": CREATED_QUERY in request.GET,
        "sent": SENT_QUERY in request.GET,
        "pending": selectors.accounts_awaiting_verification(actor),
    }
    return render(request, "web/accounts.html", context, status=status)


@requires(Permission.ACCOUNTS_CREATE)
@never_cache
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """Show the form that creates an account, and the accounts that await verification."""
    return _page(request, _actor(request))


@requires(Permission.ACCOUNTS_CREATE)
@never_cache
@csrf_protect
@require_POST
def create(request: HttpRequest) -> HttpResponse:
    """Create an account that awaits verification, and send its verification message."""
    actor = _actor(request)
    form = AccountCreationForm(request.POST)
    if not form.is_valid():
        return _page(request, actor, form=form, error=INVALID_MESSAGE, status=400)
    try:
        created = services.create_user(
            actor=actor,
            email=form.cleaned_data["email"],
            role=Role(form.cleaned_data["role"]),
            source=source(request),
            activation_url=activation_url,
        )
    except ValidationError as error:
        return _page(request, actor, form=form, error=" ".join(error.messages), status=400)
    if not created.verification_sent:
        return _page(request, actor, error=NOT_SENT_MESSAGE, status=502)
    return HttpResponseRedirect(f"{reverse('accounts')}?{CREATED_QUERY}=1")


@requires(Permission.ACCOUNTS_CREATE)
@never_cache
@csrf_protect
@require_POST
def send_verification(request: HttpRequest, user_id: int) -> HttpResponse:
    """Send the verification message of one account that awaits verification again."""
    actor = _actor(request)
    try:
        sent = services.send_account_verification(
            actor=actor, user_id=user_id, source=source(request), activation_url=activation_url
        )
    except AccountChangeError:
        return _page(request, actor, error=NOT_PENDING_MESSAGE, status=409)
    if not sent:
        return _page(request, actor, error=NOT_SENT_MESSAGE, status=502)
    return HttpResponseRedirect(f"{reverse('accounts')}?{SENT_QUERY}=1")
