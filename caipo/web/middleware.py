import logging
from collections.abc import Callable
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from caipo.accounts import selectors
from caipo.core.correlation import CORRELATION_ATTRIBUTE, correlation_scope
from caipo.web.access import PUBLIC, declared_access
from caipo.web.sessions import authentication_context

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware:
    """Give every request a correlation ID that its log lines carry (NFR-06).

    Listed first, so that the other middleware log under the ID too. The ID is
    also kept on the request, because Django logs its summary of an error
    response after every middleware has returned.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with correlation_scope() as correlation_id:
            setattr(request, CORRELATION_ATTRIBUTE, correlation_id)
            return self.get_response(request)


class AccessDeclarationMiddleware:
    """Enforce the access each view declares, and refuse a view that declares none.

    Deny by default: forgetting a declaration closes the view, it does not
    open it. Listed after AuthenticationMiddleware, which establishes who is
    asking. The account and its assurance come from the server-side session,
    and its roles from the database; nothing in the request can name a role or
    claim a second factor.

    This guards the HTTP boundary only. A service checks again for itself.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., HttpResponse],
        view_args: tuple[Any, ...],
        view_kwargs: dict[str, Any],
    ) -> None:
        access = declared_access(view_func)
        if access is None:
            logger.warning(
                "Refused a view with no access declaration",
                extra={"event": "access.undeclared_view", "view": view_func.__qualname__},
            )
            raise PermissionDenied
        if access == PUBLIC:
            return
        if not selectors.can(authentication_context(request), access):
            logger.warning(
                "Refused a view to an account without the declared permission",
                extra={
                    "event": "access.denied",
                    "view": view_func.__qualname__,
                    "permission": access.value,
                    "user_id": request.user.pk,
                },
            )
            raise PermissionDenied
