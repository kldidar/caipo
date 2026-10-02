from django.urls import path

from caipo.web import authentication, health

urlpatterns = [
    path("health/live/", health.live, name="health-live"),
    path("health/ready/", health.ready, name="health-ready"),
    path("login/", authentication.sign_in, name="login"),
    path("logout/", authentication.sign_out, name="logout"),
]
