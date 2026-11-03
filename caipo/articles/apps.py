from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ArticlesConfig(AppConfig):
    name = "caipo.articles"
    label = "articles"
    verbose_name = _("Articles")
