"""The economic transformation pages of the demonstrator (ADR-0020).

Indicators are shown in their three layers, which are never combined, and
for one class of data at a time: the study countries' reference values and
the synthetic demonstration countries never share a chart. Every chart shows
each country's gaps as gaps, says how many years hold a value, and offers
the values as a table. An indicator's page also shows the formal events of
the core AI policy corpus of the same countries, in a panel of their own on
the same years (FR-42), with the notice that this is not a causal analysis.
"""

import uuid

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from caipo.accounts import selectors as accounts_selectors
from caipo.accounts.selectors import Permission
from caipo.core.data_class import DataClass
from caipo.indicators import selectors, services
from caipo.indicators.selectors import Layer
from caipo.policies import selectors as policies_selectors
from caipo.sources import selectors as sources_selectors
from caipo.web.access import requires
from caipo.web.charts import event_axis, line_chart
from caipo.web.workspace import FORM_ERROR, REFUSED, actor_of
from caipo.web.workspace_forms import IndicatorForm


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def compare(request: HttpRequest) -> HttpResponse:
    """Compare countries layer by layer: `?class=reference|demonstration` and `?layer=A|B|C`."""
    actor = actor_of(request)
    chosen = request.GET.get("class", "")
    data_class = chosen if chosen in DataClass.values else str(DataClass.REFERENCE)
    layer = request.GET.get("layer", "")
    layer = layer if layer in Layer.values else str(Layer.STRUCTURAL)
    views = selectors.layer_view(actor, layer=layer, data_class=data_class)
    return render(
        request,
        "web/indicators.html",
        {
            "data_class": data_class,
            "layer": layer,
            "layer_label": Layer(layer).label,
            "layers": Layer.choices,
            "coverage": selectors.coverage(actor, data_class=data_class),
            "indicators": [(view, line_chart(view)) for view in views],
            "may_contribute": accounts_selectors.can(actor, Permission.RESEARCH_CONTRIBUTE),
        },
    )


@requires(Permission.RESEARCH_CONTRIBUTE)
@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def create(request: HttpRequest) -> HttpResponse:
    """Show the form for a new indicator, and record it on POST.

    Records the indicator only. Its values come from a provider's release
    file, imported through the services: the demonstrator has no upload of
    datasets (ADR-0020 point 3).
    """
    actor = actor_of(request)
    form = IndicatorForm(request.POST if request.method == "POST" else None)
    form.offer(
        "source",
        [
            (str(public_id), f"{name} ({DataClass(data_class).label})")
            for public_id, name, data_class in sources_selectors.source_choices(actor)
        ],
    )
    error = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                # The form offers only the identifiers of registered sources.
                public_id = services.create_indicator(
                    actor=actor,
                    source=uuid.UUID(data["source"]),
                    code=data["code"],
                    name=data["name"],
                    unit=data["unit"],
                    layer=data["layer"],
                    layer_reason=data["layer_reason"],
                    definition=data["definition"],
                    original_provider=data["original_provider"],
                )
            except REFUSED as refusal:
                error = str(refusal)
            else:
                return HttpResponseRedirect(reverse("indicator", args=[public_id]))
        else:
            error = str(FORM_ERROR)
    return render(
        request,
        "web/indicator_new.html",
        {"form": form, "error": error},
        status=400 if error else 200,
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show an indicator with its provenance, releases, chart, every value, and policy events."""
    actor = actor_of(request)
    found = selectors.indicator_detail(actor, public_id)
    if found is None:
        raise Http404
    events = policies_selectors.formal_events(
        actor,
        data_class=found.view.data_class,
        countries=[series.alpha2 for series in found.view.series],
    )
    return render(
        request,
        "web/indicator.html",
        {
            "detail": found,
            "view": found.view,
            "chart": line_chart(found.view),
            "events": events,
            "event_axis": event_axis(found.view, events),
        },
    )
