"""The help pages (ADR-0025 point 3): CAIPO's own text about itself, from the repository.

They are public: they describe the site and hold no record. Each section has
the anchor the help assistant's answers link to. The text is shown escaped,
paragraph by paragraph, never as HTML.
"""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from caipo.retrieval import selectors as retrieval_selectors
from caipo.web.access import public


@public
@require_safe
def help_index(request: HttpRequest) -> HttpResponse:
    """List the help pages and their sections."""
    return render(request, "web/help.html", {"pages": retrieval_selectors.help_corpus()})


@public
@require_safe
def help_page(request: HttpRequest, page: str) -> HttpResponse:
    """Show one help page, each section under its own anchor."""
    found = next((entry for entry in retrieval_selectors.help_corpus() if entry.page == page), None)
    if found is None:
        raise Http404
    return render(request, "web/help_page.html", {"page": found})
