"""Pages that show the history of recoveries of a lost second factor (ADR-0017 point 78).

Two pages, and both only read. One shows an account the recoveries of its own
second factor; the other shows an Administrator those of every account. Which
events are shown, what is shown of each, and who may see them are decided by
`caipo.accounts.selectors`: these views handle the request and nothing else,
and no page here changes anything.

Neither page takes an account from the browser. The only thing read from the
request is which page of the history is wanted.
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from caipo.accounts import selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.web import sessions
from caipo.web.access import requires

PAGE_PARAMETER = "page"


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _page_number(request: HttpRequest) -> int:
    """Return which page of the history is asked for. Anything that is not a number is the first."""
    try:
        return int(request.GET.get(PAGE_PARAMETER, "1"))
    except ValueError:
        return 1


@requires(Permission.MFA_MANAGE_OWN)
@never_cache
@require_GET
def own(request: HttpRequest) -> HttpResponse:
    """Show the signed-in account the history of the recoveries of its own second factor.

    Reached on a password alone: an account whose second factor was just
    revoked has none to give a code from.
    """
    history = selectors.recovery_history_of(_actor(request), page=_page_number(request))
    context = {"history": history, "every_account": False, "page_parameter": PAGE_PARAMETER}
    return render(request, "web/recovery_history.html", context)


@requires(Permission.MFA_RECOVERY_AUTHORIZE)
@never_cache
@require_GET
def every_account(request: HttpRequest) -> HttpResponse:
    """Show an Administrator the history of the recoveries of every account."""
    history = selectors.recoveries_on_record(_actor(request), page=_page_number(request))
    context = {"history": history, "every_account": True, "page_parameter": PAGE_PARAMETER}
    return render(request, "web/recovery_history.html", context)
