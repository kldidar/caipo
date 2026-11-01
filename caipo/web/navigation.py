"""The navigation that every page shows to a signed-in account.

A context processor. An item is shown only to an account that may open the
page it leads to, and that is read from the access the page's view declares
(`caipo.web.access`), so the navigation cannot offer a page its view refuses
and cannot hide one its view allows.
"""

from dataclasses import dataclass

from django.http import HttpRequest
from django.urls import resolve, reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from caipo.accounts import selectors
from caipo.accounts.selectors import Permission
from caipo.web import sessions
from caipo.web.access import PUBLIC, declared_access


@dataclass(frozen=True)
class NavItem:
    label: str | Promise
    url: str
    current: bool


@dataclass(frozen=True)
class NavGroup:
    label: str | Promise
    items: tuple[NavItem, ...]


@dataclass(frozen=True)
class Navigation:
    initials: str
    groups: tuple[NavGroup, ...]
    account_items: tuple[NavItem, ...]
    on_account_page: bool


# Each entry: the route's name, its label, and the routes under which it is
# the current section. Registry routes are matched by their common prefix.
type _Entry = tuple[str, str | Promise, frozenset[str]]

_WORKSPACE: tuple[_Entry, ...] = (
    ("home", _("Overview"), frozenset({"home"})),
    ("registry", _("Registry"), frozenset({"registry*"})),
)
_ADMINISTRATION: tuple[_Entry, ...] = (
    (
        "accounts",
        _("Accounts"),
        frozenset({"accounts", "account-create", "account-send-verification"}),
    ),
    (
        "second-factor-requests",
        _("Verification requests"),
        frozenset(
            {
                "second-factor-requests",
                "second-factor-request-approve",
                "second-factor-request-reject",
            }
        ),
    ),
    (
        "recovery-requests",
        _("Recovery requests"),
        frozenset({"recovery-requests", "recovery-request-authorize", "recovery-request-reject"}),
    ),
    ("recoveries", _("Recoveries"), frozenset({"recoveries"})),
)
_ACCOUNT: tuple[_Entry, ...] = (
    (
        "second-factor",
        _("Two-step verification"),
        frozenset(
            {
                "second-factor",
                "second-factor-enrol",
                "second-factor-confirm",
                "second-factor-disable",
                "second-factor-replace",
                "second-factor-history",
            }
        ),
    ),
)


def _may_open(route: str, held: frozenset[Permission]) -> bool:
    access = declared_access(resolve(reverse(route)).func)
    if access == PUBLIC:
        return True
    return isinstance(access, Permission) and access in held


def _is_current(current_route: str, section: frozenset[str]) -> bool:
    return any(
        current_route.startswith(name[:-1]) if name.endswith("*") else current_route == name
        for name in section
    )


def _items(
    entries: tuple[_Entry, ...], held: frozenset[Permission], current_route: str
) -> tuple[NavItem, ...]:
    return tuple(
        NavItem(label=label, url=reverse(route), current=_is_current(current_route, section))
        for route, label, section in entries
        if _may_open(route, held)
    )


def _initials(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = [part for part in local.replace("_", ".").replace("-", ".").split(".") if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return local[:2].upper()


def navigation(request: HttpRequest) -> dict[str, Navigation | None]:
    """Return the navigation of the signed-in account, or None for anyone else."""
    actor = sessions.authentication_context(request)
    if actor is None:
        return {"navigation": None}
    held = selectors.permissions_of(actor)
    match = request.resolver_match
    current_route = (match.url_name or "") if match is not None else ""
    email = str(getattr(request.user, "email", ""))
    groups = tuple(
        group
        for group in (
            NavGroup(_("Workspace"), _items(_WORKSPACE, held, current_route)),
            NavGroup(_("Administration"), _items(_ADMINISTRATION, held, current_route)),
        )
        if group.items
    )
    return {
        "navigation": Navigation(
            initials=_initials(email),
            groups=groups,
            account_items=_items(_ACCOUNT, held, current_route),
            on_account_page=current_route == "login",
        )
    }
