import logging
from collections.abc import Callable
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from caipo.core.correlation import CORRELATION_ATTRIBUTE, correlation_scope
from caipo.web.access import declared_access

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
    """Refuse any view that does not declare the access it requires.

    Deny by default: forgetting a declaration closes the view, it does not
    open it.
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
        if declared_access(view_func) is None:
            logger.warning(
                "Refused a view with no access declaration",
                extra={"event": "access.undeclared_view", "view": view_func.__qualname__},
            )
            raise PermissionDenied
