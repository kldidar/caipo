"""Template filters for indicator values: they change how a value looks, never what it is."""

from decimal import Decimal

from django import template

from caipo.web.charts import format_value

register = template.Library()


@register.filter
def value(number: Decimal | None) -> str:
    """Show a value with at most two decimals, or nothing if there is none."""
    return "" if number is None else format_value(number)


@register.filter
def index(sequence: tuple[object, ...], position: int) -> object:
    """Return the item at a position of a sequence."""
    return sequence[position]
