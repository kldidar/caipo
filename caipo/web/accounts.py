"""Pages on which an Administrator creates accounts, changes their roles, and
disables and enables them (ADR-0015).

These views handle the request and nothing else. Who may do what, which roles
exist, and what is recorded are decided by `caipo.accounts`. A change is made
by POST with a CSRF token. The acting Administrator comes from the session; a
form supplies an email address, a role, a reason, or a confirmation, and never
a password. The account a change applies to is named by its number in the
address, and the service checks the permission before it looks that number up.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from caipo.accounts import selectors, services
from caipo.accounts.selectors import AuthenticationContext, Permission, Role
from caipo.accounts.services import (
    AccountChangeError,
    LastAdministratorError,
    NoSuchAccountError,
    RoleChangeError,
)
from caipo.web import sessions
from caipo.web.access import requires
from caipo.web.activation import activation_url
from caipo.web.authentication import source
from caipo.web.forms import AccountCreationForm, DisableAccountForm, RoleChangeForm

INVALID_MESSAGE = _("Give an email address and choose one of the roles.")
NOT_SENT_MESSAGE = _(
    "The account exists, but its verification message could not be sent. Send it again below."
)
NOT_PENDING_MESSAGE = _("That account does not await verification.")
CREATED_QUERY = "created"
SENT_QUERY = "sent"

ROLE_INVALID_MESSAGE = _("Choose one of the roles and give a reason.")
HOLDS_ROLE_MESSAGE = _("The account already holds that role.")
LACKS_ROLE_MESSAGE = _("The account does not hold that role.")
LAST_ADMINISTRATOR_MESSAGE = _("That would leave the system with no Administrator.")
CONFIRM_MESSAGE = _("Tick the confirmation to disable the account.")
ALREADY_DISABLED_MESSAGE = _("The account is already disabled.")
NOT_DISABLED_MESSAGE = _("The account is not disabled.")
CHANGED_QUERY = "changed"
# What the page says after a change, by the value of CHANGED_QUERY. Anything
# else in the address says nothing.
CHANGE_MESSAGES = {
    "granted": _("The role was granted. It takes effect on the account's next request."),
    "revoked": _("The role was revoked. It takes effect on the account's next request."),
    "disabled": _("The account was disabled. Its sessions end on their next request."),
    "enabled": _("The account was enabled, with the roles and second factor it had."),
    "enabled-unverified": _(
        "The account was enabled. It had never been activated, so its verification message"
        " must be sent again from the list of accounts."
    ),
}


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
        "accounts": (
            selectors.accounts_for_administration(actor)
            if selectors.can(actor, Permission.ROLES_MANAGE)
            else None
        ),
    }
    return render(request, "web/accounts.html", context, status=status)


def _account_page(
    request: HttpRequest,
    actor: AuthenticationContext,
    user_id: int,
    *,
    grant_form: RoleChangeForm | None = None,
    revoke_form: RoleChangeForm | None = None,
    disable_form: DisableAccountForm | None = None,
    error: Promise | str | None = None,
    status: int = 200,
) -> HttpResponse:
    account = selectors.account_for_administration(actor, user_id)
    if account is None:
        raise Http404
    # Each form offers only the roles it can apply to. It still accepts any of
    # the four, so that a stale page reaches the service and is told why.
    if grant_form is None:
        grant_form = RoleChangeForm(auto_id="grant_%s")
    if revoke_form is None:
        revoke_form = RoleChangeForm(auto_id="revoke_%s")
    grant_form.offer(account.grantable)
    revoke_form.offer(account.summary.roles)
    context = {
        "account": account,
        "grant_form": grant_form,
        "revoke_form": revoke_form,
        "disable_form": disable_form or DisableAccountForm(),
        "error": error,
        "changed": CHANGE_MESSAGES.get(request.GET.get(CHANGED_QUERY, "")),
    }
    return render(request, "web/account.html", context, status=status)


def _changed(user_id: int, change: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"{reverse('account', args=[user_id])}?{CHANGED_QUERY}={change}")


@requires(Permission.ACCOUNTS_CREATE)
@never_cache
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """Show the account creation form, the accounts awaiting verification, and all accounts."""
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


@requires(Permission.ROLES_MANAGE)
@never_cache
@require_GET
def detail(request: HttpRequest, user_id: int) -> HttpResponse:
    """Show one account, its role history, and the changes that can be made to it."""
    return _account_page(request, _actor(request), user_id)


@requires(Permission.ROLES_MANAGE)
@never_cache
@csrf_protect
@require_POST
def grant_role(request: HttpRequest, user_id: int) -> HttpResponse:
    """Grant one role to an account, with the reason given."""
    actor = _actor(request)
    form = RoleChangeForm(request.POST, auto_id="grant_%s")
    if not form.is_valid():
        return _account_page(
            request, actor, user_id, grant_form=form, error=ROLE_INVALID_MESSAGE, status=400
        )
    try:
        services.grant_role_to_account(
            actor=actor,
            user_id=user_id,
            role=Role(form.cleaned_data["role"]),
            reason=form.cleaned_data["reason"],
        )
    except NoSuchAccountError as error:
        raise Http404 from error
    except RoleChangeError:
        return _account_page(request, actor, user_id, error=HOLDS_ROLE_MESSAGE, status=409)
    return _changed(user_id, "granted")


@requires(Permission.ROLES_MANAGE)
@never_cache
@csrf_protect
@require_POST
def revoke_role(request: HttpRequest, user_id: int) -> HttpResponse:
    """Revoke one role from an account, with the reason given."""
    actor = _actor(request)
    form = RoleChangeForm(request.POST, auto_id="revoke_%s")
    if not form.is_valid():
        return _account_page(
            request, actor, user_id, revoke_form=form, error=ROLE_INVALID_MESSAGE, status=400
        )
    try:
        services.revoke_role_from_account(
            actor=actor,
            user_id=user_id,
            role=Role(form.cleaned_data["role"]),
            reason=form.cleaned_data["reason"],
        )
    except NoSuchAccountError as error:
        raise Http404 from error
    except LastAdministratorError:
        return _account_page(request, actor, user_id, error=LAST_ADMINISTRATOR_MESSAGE, status=409)
    except RoleChangeError:
        return _account_page(request, actor, user_id, error=LACKS_ROLE_MESSAGE, status=409)
    return _changed(user_id, "revoked")


@requires(Permission.ACCOUNTS_DEACTIVATE)
@never_cache
@csrf_protect
@require_POST
def disable(request: HttpRequest, user_id: int) -> HttpResponse:
    """Disable an account, once the confirmation is ticked."""
    actor = _actor(request)
    form = DisableAccountForm(request.POST)
    if not form.is_valid():
        return _account_page(
            request, actor, user_id, disable_form=form, error=CONFIRM_MESSAGE, status=400
        )
    try:
        services.disable_account(actor=actor, user_id=user_id)
    except NoSuchAccountError as error:
        raise Http404 from error
    except LastAdministratorError:
        return _account_page(request, actor, user_id, error=LAST_ADMINISTRATOR_MESSAGE, status=409)
    except AccountChangeError:
        return _account_page(request, actor, user_id, error=ALREADY_DISABLED_MESSAGE, status=409)
    return _changed(user_id, "disabled")


@requires(Permission.ACCOUNTS_ENABLE)
@never_cache
@csrf_protect
@require_POST
def enable(request: HttpRequest, user_id: int) -> HttpResponse:
    """Enable a disabled account."""
    actor = _actor(request)
    try:
        state = services.enable_account(actor=actor, user_id=user_id)
    except NoSuchAccountError as error:
        raise Http404 from error
    except AccountChangeError:
        return _account_page(request, actor, user_id, error=NOT_DISABLED_MESSAGE, status=409)
    return _changed(
        user_id, "enabled" if state == selectors.AccountStatus.ACTIVE else "enabled-unverified"
    )
