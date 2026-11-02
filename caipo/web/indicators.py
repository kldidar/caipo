"""The economic transformation pages of the demonstrator (ADR-0020).

Indicators are shown in their three layers, which are never combined, and
for one class of data at a time: the study countries' reference values and
the synthetic demonstration countries never share a chart. Every chart shows
each country's gaps as gaps, says how many years hold a value, and offers
the values as a table.
"""

import uuid

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from caipo.accounts.selectors import Permission
from caipo.core.data_class import DataClass
from caipo.indicators import selectors
from caipo.indicators.selectors import Layer
from caipo.web.access import requires
from caipo.web.charts import line_chart
from caipo.web.workspace import actor_of


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
        },
    )


@requires(Permission.WORKSPACE_READ)
@never_cache
@require_safe
def detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Show an indicator with its provenance, releases, chart, and every value."""
    found = selectors.indicator_detail(actor_of(request), public_id)
    if found is None:
        raise Http404
    return render(
        request,
        "web/indicator.html",
        {"detail": found, "view": found.view, "chart": line_chart(found.view)},
    )
