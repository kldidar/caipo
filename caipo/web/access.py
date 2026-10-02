"""Access declarations for views (ADR-0007 rule 1, NFR-11).

Every view declares the access it requires: `public`, or `requires` with a
permission. A view with no declaration is refused by
AccessDeclarationMiddleware.

A declaration states what a view needs; it decides nothing. The decision is
made by `caipo.accounts.selectors`, the same code that services call, so the
HTTP boundary and the service layer cannot disagree about who may do what.
"""

from collections.abc import Callable
from typing import Final, Literal

from caipo.accounts.selectors import Permission

PUBLIC: Final = "public"

type Access = Literal["public"] | Permission

_ATTRIBUTE = "caipo_access"


def public[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Declare that a view may be reached by anyone, including anonymous visitors.

    Apply it outermost, so that the declaration is on the callable the URL
    configuration holds.
    """
    setattr(view, _ATTRIBUTE, PUBLIC)
    return view


def requires[**P, R](permission: Permission) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare that a view may be reached only by an account holding a permission.

    Apply it outermost. Raises TypeError when the module is imported if the
    argument is not a Permission, so a misspelt or invented permission cannot
    be declared.
    """
    if not isinstance(permission, Permission):
        raise TypeError("requires() takes a Permission.")

    def declare(view: Callable[P, R]) -> Callable[P, R]:
        setattr(view, _ATTRIBUTE, permission)
        return view

    return declare


def declared_access(view: Callable[..., object]) -> Access | None:
    """Return the access a view declares, or None if it declares none.

    Anything other than the two forms above counts as no declaration.
    """
    access = getattr(view, _ATTRIBUTE, None)
    if isinstance(access, Permission):
        return access
    if access == PUBLIC:
        return PUBLIC
    return None
