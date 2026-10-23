"""The pages answered when a request is refused, names nothing, or fails.

They are Django's error handlers, named in the root URL configuration, and
no route leads to them. None of them shows the exception, a path inside the
code, or anything about the account beyond what the person refused needs in
order to know what to do next. They decide nothing: a request refused here
was refused by the access declaration or by a service before it arrived.
"""

from django.http import HttpRequest, HttpResponse, HttpResponseServerError
from django.shortcuts import render
from django.template import loader
from django.utils.cache import add_never_cache_headers

from caipo.accounts import selectors
from caipo.accounts.selectors import AuthenticationContext, Permission
from caipo.web import sessions
from caipo.web.access import declared_access


def permission_denied(request: HttpRequest, exception: Exception) -> HttpResponse:
    """Answer a refusal with 403 and a page that says what the person can do about it.

    An anonymous visitor is offered the sign-in page, and comes back to the
    page asked for if it was asked for by GET. An account that would hold the
    permission the page declares once it signs in with a trusted second
    factor is told so. Any other account is told only that it has no access.
    The answer is never stored by a cache, because it depends on who asked.
    """
    context = _context(request)
    if context is None:
        situation = "anonymous"
    elif _second_factor_would_grant(request, context):
        situation = "second_factor"
    else:
        situation = "not_permitted"
    response = render(
        request,
        "web/403.html",
        {
            "situation": situation,
            "next": request.get_full_path() if request.method == "GET" else "",
        },
        status=403,
    )
    add_never_cache_headers(response)
    return response


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    """Answer 404 with a page that names neither the path nor the reason."""
    return render(request, "web/404.html", status=404)


def server_error(request: HttpRequest) -> HttpResponse:
    """Answer 500 with a page that depends on nothing that may itself have failed.

    It is rendered without the request, so that no context processor, session,
    or database query runs, and it says nothing about the failure.
    """
    response = HttpResponseServerError(loader.get_template("web/500.html").render())
    add_never_cache_headers(response)
    return response


def _context(request: HttpRequest) -> AuthenticationContext | None:
    # A refusal raised before the session and the account were established
    # has no account to speak of.
    if not hasattr(request, "user") or not hasattr(request, "session"):
        return None
    return sessions.authentication_context(request)


def _second_factor_would_grant(request: HttpRequest, context: AuthenticationContext) -> bool:
    match = getattr(request, "resolver_match", None)
    access = declared_access(match.func) if match is not None else None
    return isinstance(access, Permission) and selectors.second_factor_would_grant(context, access)
