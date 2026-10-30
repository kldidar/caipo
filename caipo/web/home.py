"""The home page: what CAIPO is, and for a signed-in account, an overview of the workspace."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import Permission
from caipo.registry import selectors as registry_selectors
from caipo.web import sessions
from caipo.web.access import public


@public
@never_cache
@require_safe
def home(request: HttpRequest) -> HttpResponse:
    """Describe CAIPO to anyone; give a signed-in account an overview of what it can reach.

    Public: an anonymous visitor is shown what the platform is and how it
    treats evidence, and no record. A signed-in account is shown the counts of
    the records it may read, and links to the pages it may open.
    """
    actor = sessions.authentication_context(request)
    if actor is None:
        return render(request, "web/home_public.html")
    registry = None
    if accounts_selectors.can(actor, Permission.REGISTRY_READ):
        institutions = registry_selectors.institutions(actor)
        registry = {
            "countries": len(registry_selectors.countries(actor)),
            "languages": len(registry_selectors.languages(actor)),
            "institutions": len(institutions),
            "names": sum(len(institution.names) for institution in institutions),
        }
    context = {
        "registry": registry,
        "may_enter_registry": accounts_selectors.can(
            actor, Permission.REGISTRY_INSTITUTIONS_MANAGE
        ),
        "may_administer": accounts_selectors.can(actor, Permission.ACCOUNTS_CREATE),
    }
    return render(request, "web/home.html", context)
