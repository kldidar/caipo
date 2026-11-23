"""The page about CAIPO, for a reader from outside the project.

Public: it is the repository's own account of the project, and holds no
record. It says what CAIPO is for, what this site holds, what is real and
what is synthetic, how the assistants were evaluated, and how CAIPO is built.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from caipo.web.access import public

# The evaluation report of Day 43, by its path in the repository.
EVALUATION_REPORT = "docs/reports/evaluation-day43-assistants.md"


@public
@require_safe
def about(request: HttpRequest) -> HttpResponse:
    """Describe CAIPO, its data, its assistants, and how it is built."""
    repository = settings.SOURCE_REPOSITORY_URL
    return render(
        request,
        "web/about.html",
        {
            "repository": repository,
            "evaluation_report": f"{repository}/blob/main/{EVALUATION_REPORT}",
        },
    )
