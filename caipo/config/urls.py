"""Root URL configuration. All HTTP handling lives in the web package."""

from django.urls import include, path

urlpatterns = [
    path("", include("caipo.web.urls")),
]

handler403 = "caipo.web.errors.permission_denied"
handler404 = "caipo.web.errors.page_not_found"
handler500 = "caipo.web.errors.server_error"
