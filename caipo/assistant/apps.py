from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AssistantConfig(AppConfig):
    name = "caipo.assistant"
    label = "assistant"
    verbose_name = _("Assistant")
