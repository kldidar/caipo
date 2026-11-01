from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PoliciesConfig(AppConfig):
    name = "caipo.policies"
    label = "policies"
    verbose_name = _("Policies")
