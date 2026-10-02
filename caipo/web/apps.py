from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WebConfig(AppConfig):
    name = "caipo.web"
    label = "web"
    verbose_name = _("Web interface")
