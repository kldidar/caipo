"""The page on which an Administrator reads the general audit record (ADR-0018).

It only reads. What is shown of each change, and who may see it, are decided
by `caipo.accounts.selectors`; this view handles the request and nothing
else. The only things read from the request are the kind of record to show
and which page of the record is wanted.
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from caipo.accounts import selectors
from caipo.accounts.selectors import AuditTargetType, AuthenticationContext, Permission
from caipo.web import sessions
from caipo.web.access import requires

PAGE_PARAMETER = "page"
KIND_PARAMETER = "kind"


def _actor(request: HttpRequest) -> AuthenticationContext:
    context = sessions.authentication_context(request)
    if context is None:
        raise PermissionDenied
    return context


def _page_number(request: HttpRequest) -> int:
    """Return which page is asked for. Anything that is not a number is the first."""
    try:
        return int(request.GET.get(PAGE_PARAMETER, "1"))
    except ValueError:
        return 1


@requires(Permission.AUDIT_READ)
@never_cache
@require_GET
def record(request: HttpRequest) -> HttpResponse:
    """Show the audit record, latest change first, optionally of one kind of record."""
    page = selectors.audit_record(
        _actor(request),
        page=_page_number(request),
        target_type=request.GET.get(KIND_PARAMETER) or None,
    )
    context = {
        "record": page,
        "kinds": AuditTargetType.choices,
        "page_parameter": PAGE_PARAMETER,
        "kind_parameter": KIND_PARAMETER,
    }
    return render(request, "web/audit_record.html", context)
