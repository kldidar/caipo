from django.urls import path

from caipo.web import (
    accounts,
    activation,
    authentication,
    health,
    home,
    password_reset,
    recovery,
    recovery_history,
    recovery_requests,
    registry,
    second_factor,
    second_factor_requests,
)

urlpatterns = [
    path("", home.home, name="home"),
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
    path("account/second-factor/history/", recovery_history.own, name="second-factor-history"),
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
    path("administration/recoveries/", recovery_history.every_account, name="recoveries"),
    path("registry/", registry.browse, name="registry"),
    path("registry/entry/", registry.entry, name="registry-entry"),
    path(
        "registry/entry/countries/create/", registry.create_country, name="registry-country-create"
    ),
    path(
        "registry/entry/countries/<uuid:public_id>/rename/",
        registry.rename_country,
        name="registry-country-rename",
    ),
    path(
        "registry/entry/countries/<uuid:public_id>/deactivate/",
        registry.deactivate_country,
        name="registry-country-deactivate",
    ),
    path(
        "registry/entry/countries/<uuid:public_id>/reactivate/",
        registry.reactivate_country,
        name="registry-country-reactivate",
    ),
    path(
        "registry/entry/languages/create/",
        registry.create_language,
        name="registry-language-create",
    ),
    path(
        "registry/entry/languages/<uuid:public_id>/rename/",
        registry.rename_language,
        name="registry-language-rename",
    ),
    path(
        "registry/entry/languages/<uuid:public_id>/deactivate/",
        registry.deactivate_language,
        name="registry-language-deactivate",
    ),
    path(
        "registry/entry/languages/<uuid:public_id>/reactivate/",
        registry.reactivate_language,
        name="registry-language-reactivate",
    ),
    path(
        "registry/entry/institutions/create/",
        registry.create_institution,
        name="registry-institution-create",
    ),
    path(
        "registry/entry/institutions/<uuid:public_id>/change/",
        registry.change_institution,
        name="registry-institution-change",
    ),
    path(
        "registry/entry/institutions/<uuid:public_id>/names/add/",
        registry.add_institution_name,
        name="registry-institution-name-add",
    ),
    path(
        "registry/entry/institution-names/<uuid:public_id>/dates/",
        registry.change_institution_name_dates,
        name="registry-institution-name-dates",
    ),
    path(
        "registry/entry/institution-names/<uuid:public_id>/mark-entered-in-error/",
        registry.mark_institution_name_entered_in_error,
        name="registry-institution-name-mark",
    ),
]
