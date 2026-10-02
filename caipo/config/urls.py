"""Root URL configuration. All HTTP handling lives in the web package."""

from django.urls import include, path

urlpatterns = [
    path("", include("caipo.web.urls")),
]
