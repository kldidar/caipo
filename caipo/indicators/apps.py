from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IndicatorsConfig(AppConfig):
    name = "caipo.indicators"
    label = "indicators"
    verbose_name = _("Indicators")
