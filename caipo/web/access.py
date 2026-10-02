"""Access declarations for views (ADR-0007 rule 1, NFR-11).

Every view declares the access it requires. `public` is the only declaration
so far; declarations for the four roles and for administration arrive with
roles. A view with no declaration is refused by AccessDeclarationMiddleware.
"""

from collections.abc import Callable

PUBLIC = "public"

_ATTRIBUTE = "caipo_access"


def public[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Declare that a view may be reached by anyone, including anonymous visitors.

    Apply it outermost, so that the declaration is on the callable the URL
    configuration holds.
    """
    setattr(view, _ATTRIBUTE, PUBLIC)
    return view


def declared_access(view: Callable[..., object]) -> str | None:
    """Return the access a view declares, or None if it declares none."""
    return getattr(view, _ATTRIBUTE, None)
