from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DemoConfig(AppConfig):
    name = "caipo.demo"
    label = "demo"
    verbose_name = _("Demonstration setup")
