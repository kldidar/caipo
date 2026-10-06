from django.urls import path

from caipo.web import (
    accounts,
    activation,
    authentication,
    health,
    password_reset,
    recovery,
    recovery_requests,
    second_factor,
    second_factor_requests,
)

urlpatterns = [
    path("health/live/", health.live, name="health-live"),
    path("health/ready/", health.ready, name="health-ready"),
    path("login/", authentication.sign_in, name="login"),
    path("login/verify/", authentication.verify_second_factor, name="login-verify"),
    path("login/verify/recover/", recovery.request_recovery, name="login-recover"),
    path("logout/", authentication.sign_out, name="logout"),
    path("activate/", activation.activate, name="activate"),
    path("password-reset/", password_reset.request_reset, name="password-reset"),
    path("password-reset/confirm/", password_reset.confirm_reset, name="password-reset-confirm"),
    path("administration/accounts/", accounts.overview, name="accounts"),
    path("administration/accounts/create/", accounts.create, name="account-create"),
    path(
        "administration/accounts/<int:user_id>/send-verification/",
        accounts.send_verification,
        name="account-send-verification",
    ),
    path("account/second-factor/", second_factor.overview, name="second-factor"),
    path("account/second-factor/enrol/", second_factor.enrol, name="second-factor-enrol"),
    path("account/second-factor/confirm/", second_factor.confirm, name="second-factor-confirm"),
    path("account/second-factor/disable/", second_factor.disable, name="second-factor-disable"),
    path("account/second-factor/replace/", second_factor.replace, name="second-factor-replace"),
    path(
        "administration/second-factor-requests/",
        second_factor_requests.overview,
        name="second-factor-requests",
    ),
    path(
        "administration/second-factor-requests/<int:number>/approve/",
        second_factor_requests.approve,
        name="second-factor-request-approve",
    ),
    path(
        "administration/second-factor-requests/<int:number>/reject/",
        second_factor_requests.reject,
        name="second-factor-request-reject",
    ),
    path(
        "administration/recovery-requests/",
        recovery_requests.overview,
        name="recovery-requests",
    ),
    path(
        "administration/recovery-requests/<int:number>/authorize/",
        recovery_requests.authorize,
        name="recovery-request-authorize",
    ),
    path(
        "administration/recovery-requests/<int:number>/reject/",
        recovery_requests.reject,
        name="recovery-request-reject",
    ),
]
