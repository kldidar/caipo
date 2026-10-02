"""No second factor exists, and nothing in the running application can pretend one does.

The only way to stand in for an enrolled second factor is the `mfa_enrolled`
test fixture, which replaces a function in the memory of the test process.
"""

import ast
import inspect
from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.exceptions import PermissionDenied

import caipo
from caipo.accounts import mfa, selectors, services
from caipo.accounts.models import User
from caipo.accounts.selectors import Permission, Role
from caipo.accounts.tests.fixtures import UserFactory

PACKAGE_ROOT = Path(inspect.getfile(caipo)).parent

# Names someone might hope would switch the requirement off.
SWITCHES = [
    "BYPASS_MFA",
    "MFA_BYPASS",
    "DISABLE_MFA",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "MFA_ENROLLED",
    "MFA_VERIFIED",
    "MFA_REQUIRED",
    "REQUIRE_MFA",
    "SKIP_MFA",
    "TOTP_BYPASS",
    "TOTP_DISABLED",
    "TESTING",
    "DEBUG",
]


def _production_modules() -> list[Path]:
    return [path for path in PACKAGE_ROOT.rglob("*.py") if "tests" not in path.parts]


def _holds_administrative_permission(user: User) -> bool:
    return bool(
        selectors.permissions_of(user) & {Permission.ROLES_MANAGE, Permission.ACCOUNTS_DEACTIVATE}
    )


@pytest.mark.services
@pytest.mark.django_db
def test_no_account_is_enrolled(user_with_roles: UserFactory) -> None:
    for role in Role:
        assert mfa.is_enrolled(user_with_roles(role)) is False


def test_the_enrolment_lookup_is_the_real_one_unless_a_test_replaces_it() -> None:
    assert mfa.is_enrolled.__module__ == "caipo.accounts.mfa"
    assert Path(inspect.getfile(mfa.is_enrolled)) == PACKAGE_ROOT / "accounts" / "mfa.py"


def test_the_enrolment_lookup_consults_nothing() -> None:
    (function,) = [
        node for node in ast.parse(inspect.getsource(mfa)).body if isinstance(node, ast.FunctionDef)
    ]
    statements = [node for node in function.body if not isinstance(node, ast.Expr)]

    # After its docstring, the function is exactly `return False`.
    assert function.name == "is_enrolled"
    assert len(statements) == 1
    assert isinstance(statements[0], ast.Return)
    assert isinstance(statements[0].value, ast.Constant)
    assert statements[0].value.value is False


def test_the_enrolment_module_reads_no_environment_setting_or_request() -> None:
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(ast.parse(inspect.getsource(mfa)))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }

    assert imported == {"caipo.accounts.models"}


def test_no_production_module_can_replace_the_enrolment_lookup() -> None:
    offenders = []
    for path in _production_modules():
        source = path.read_text()
        if path.name != "mfa.py" and "is_enrolled" in source:
            # The one legitimate use: the selector calls it.
            if path.name == "selectors.py" and source.count("is_enrolled") == 1:
                assert "mfa.is_enrolled(user)" in source
                continue
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))
        if "monkeypatch" in source or ".tests" in source or "import pytest" in source:
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))

    assert _production_modules(), "no production modules were found to check"
    assert offenders == []


def test_no_setting_mentions_a_second_factor(settings: LazySettings) -> None:
    names = [name for name in dir(settings) if name.isupper()]

    assert [name for name in names if "MFA" in name or "TOTP" in name or "OTP" in name] == []


@pytest.mark.services
@pytest.mark.django_db
@pytest.mark.parametrize("value", ["true", "1", "True", "yes", "on"])
def test_no_environment_variable_enables_administrator_privileges(
    user_with_roles: UserFactory, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    for name in SWITCHES:
        for variable in (name, f"CAIPO_{name}", f"DJANGO_{name}"):
            monkeypatch.setenv(variable, value)

    assert mfa.is_enrolled(administrator) is False
    assert not _holds_administrative_permission(administrator)


@pytest.mark.services
@pytest.mark.django_db
def test_no_setting_enables_administrator_privileges(
    user_with_roles: UserFactory, settings: LazySettings
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    for name in SWITCHES:
        setattr(settings, name, name != "MFA_REQUIRED" and name != "REQUIRE_MFA")

    assert mfa.is_enrolled(administrator) is False
    assert not _holds_administrative_permission(administrator)


@pytest.mark.services
@pytest.mark.django_db
def test_no_value_on_the_account_enables_administrator_privileges(
    user_with_roles: UserFactory,
) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR, Role.REVIEWER)
    for attribute in ("mfa_enrolled", "mfa_verified", "is_verified", "otp_device", "totp_enrolled"):
        setattr(administrator, attribute, True)
    administrator.save()

    stored = User.objects.get(pk=administrator.pk)
    assert mfa.is_enrolled(administrator) is False
    assert selectors.permissions_of(administrator) == frozenset()
    assert selectors.permissions_of(stored) == frozenset()


@pytest.mark.services
@pytest.mark.django_db
def test_the_account_table_has_no_column_that_could_record_enrolment() -> None:
    columns = {field.column for field in User._meta.concrete_fields}

    assert columns == {
        "id",
        "password",
        "last_login",
        "email",
        "is_active",
        "created_at",
        "updated_at",
    }


@pytest.mark.services
@pytest.mark.django_db
def test_without_the_fixture_an_administrator_cannot_act(user_with_roles: UserFactory) -> None:
    administrator = user_with_roles(Role.ADMINISTRATOR)
    other = user_with_roles(Role.ADMINISTRATOR)

    with pytest.raises(PermissionDenied):
        services.grant_role(
            actor=administrator, user=other, role=Role.READER, reason="TEST attempt"
        )

    assert selectors.roles_of(other) == {Role.ADMINISTRATOR}


@pytest.mark.services
@pytest.mark.django_db
@pytest.mark.usefixtures("mfa_enrolled")
def test_the_fixture_lasts_for_one_test_only_first_half(user_with_roles: UserFactory) -> None:
    assert _holds_administrative_permission(user_with_roles(Role.ADMINISTRATOR))


@pytest.mark.services
@pytest.mark.django_db
def test_the_fixture_lasts_for_one_test_only_second_half(user_with_roles: UserFactory) -> None:
    # Runs after the test above, which used the fixture.
    assert mfa.is_enrolled.__module__ == "caipo.accounts.mfa"
    assert not _holds_administrative_permission(user_with_roles(Role.ADMINISTRATOR))
