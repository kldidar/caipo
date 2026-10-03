"""The state invariants of a second factor, enforced by PostgreSQL."""

from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from caipo.accounts.models import MfaChallenge, TotpDevice, TotpDeviceState, User

pytestmark = [pytest.mark.services, pytest.mark.django_db]

# Visibly synthetic: not a ciphertext of anything.
CIPHERTEXT = b"TEST-not-a-real-ciphertext"


@pytest.fixture
def user() -> User:
    return User.objects.create_user("test.reader@caipo.test")


def _device(user: User, **values: Any) -> TotpDevice:
    defaults = {
        "state": TotpDeviceState.PENDING_VERIFICATION,
        "secret_ciphertext": CIPHERTEXT,
        "key_id": "TEST",
    }
    return TotpDevice.objects.create(user=user, **(defaults | values))


def _active() -> dict[str, Any]:
    return {"state": TotpDeviceState.ACTIVE, "confirmed_at": timezone.now(), "last_used_step": 1}


def _approved(by: User | None = None) -> dict[str, Any]:
    return {"approved_at": timezone.now(), "approved_by": by}


def test_the_states_are_exactly_these_three() -> None:
    assert TotpDeviceState.values == ["pending_approval", "pending_verification", "active"]


def test_a_pending_and_an_active_device_can_be_stored(user: User) -> None:
    other = User.objects.create_user("test.other@caipo.test")

    third = User.objects.create_user("test.third@caipo.test")

    assert _device(user).state == "pending_verification"
    assert _device(other, **_active()).state == "active"
    assert _device(third, state=TotpDeviceState.PENDING_APPROVAL).state == "pending_approval"


@pytest.mark.parametrize(
    "state", ["enabled", "verified", "disabled", "", "ACTIVE", "pending", "approved", "trusted"]
)
def test_the_database_rejects_an_unknown_state(user: User, state: str) -> None:
    with pytest.raises(IntegrityError, match="accounts_totpdevice_"), transaction.atomic():
        _device(user, **(_active() | {"state": state}))


@pytest.mark.parametrize(
    "values",
    [
        {"state": "active"},
        {"state": "active", "confirmed_at": None, "last_used_step": 1},
        {"state": "active", "confirmed_at": timezone.now(), "last_used_step": None},
    ],
    ids=["neither", "no-confirmation-time", "no-accepted-code"],
)
def test_the_database_rejects_an_active_device_that_was_never_confirmed(
    user: User, values: dict[str, Any]
) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_active_iff_confirmed"),
        transaction.atomic(),
    ):
        _device(user, **values)


@pytest.mark.parametrize(
    "values",
    [{"confirmed_at": timezone.now()}, {"last_used_step": 1}],
    ids=["confirmation-time", "accepted-code"],
)
def test_the_database_rejects_a_pending_device_that_claims_confirmation(
    user: User, values: dict[str, Any]
) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_active_iff_confirmed"),
        transaction.atomic(),
    ):
        _device(user, **values)


def test_a_pending_device_cannot_be_made_active_by_changing_the_state_alone(user: User) -> None:
    device = _device(user)

    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_active_iff_confirmed"),
        transaction.atomic(),
    ):
        TotpDevice.objects.filter(pk=device.pk).update(state=TotpDeviceState.ACTIVE)

    assert TotpDevice.objects.get().state == "pending_verification"


@pytest.mark.parametrize(
    "values",
    [{"confirmed_at": timezone.now()}, {"last_used_step": 1}, _active() | {"state": None}],
    ids=["confirmation-time", "accepted-code", "both"],
)
def test_the_database_rejects_a_request_awaiting_approval_that_claims_confirmation(
    user: User, values: dict[str, Any]
) -> None:
    values = values | {"state": TotpDeviceState.PENDING_APPROVAL}

    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_active_iff_confirmed"),
        transaction.atomic(),
    ):
        _device(user, **values)


# --- Approval ------------------------------------------------------------------


def test_a_device_is_stored_unapproved_unless_something_says_otherwise(user: User) -> None:
    device = _device(user, **_active())

    assert (device.approved_at, device.approved_by) == (None, None)


@pytest.mark.parametrize("state", ["pending_verification", "active"])
def test_an_approval_naming_another_account_can_be_stored(user: User, state: str) -> None:
    approver = User.objects.create_user("test.approver@caipo.test")
    values = _active() if state == "active" else {}

    device = _device(user, **(values | _approved(approver)))

    assert device.approved_by == approver


def test_the_database_rejects_a_request_awaiting_approval_that_is_already_approved(
    user: User,
) -> None:
    approver = User.objects.create_user("test.approver@caipo.test")

    for approval in (_approved(), _approved(approver)):
        with (
            pytest.raises(
                IntegrityError, match="accounts_totpdevice_awaiting_approval_is_unapproved"
            ),
            transaction.atomic(),
        ):
            _device(user, state=TotpDeviceState.PENDING_APPROVAL, **approval)


def test_the_database_rejects_an_account_approving_its_own_device(user: User) -> None:
    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_approver_is_not_user"),
        transaction.atomic(),
    ):
        _device(user, **(_active() | _approved(user)))


def test_the_database_rejects_an_approver_without_an_approval(user: User) -> None:
    approver = User.objects.create_user("test.approver@caipo.test")

    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_approver_is_not_user"),
        transaction.atomic(),
    ):
        _device(user, **(_active() | {"approved_by": approver}))


def test_a_request_cannot_be_approved_by_its_own_account_with_an_update(user: User) -> None:
    device = _device(user, state=TotpDeviceState.PENDING_APPROVAL)

    with (
        pytest.raises(IntegrityError, match="accounts_totpdevice_approver_is_not_user"),
        transaction.atomic(),
    ):
        TotpDevice.objects.filter(pk=device.pk).update(
            state=TotpDeviceState.PENDING_VERIFICATION,
            approved_at=timezone.now(),
            approved_by=user,
        )

    assert TotpDevice.objects.get().state == "pending_approval"


def test_an_account_named_as_an_approver_cannot_be_deleted(user: User) -> None:
    approver = User.objects.create_user("test.approver@caipo.test")
    _device(user, **_approved(approver))

    with pytest.raises(ProtectedError):
        approver.delete()


@pytest.mark.parametrize("first", ["pending", "active"])
@pytest.mark.parametrize("second", ["pending", "active"])
def test_an_account_has_at_most_one_device_in_any_state(
    user: User, first: str, second: str
) -> None:
    _device(user, **(_active() if first == "active" else {}))

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        _device(user, **(_active() if second == "active" else {}))

    assert TotpDevice.objects.count() == 1


def test_an_account_has_at_most_one_pending_challenge(user: User) -> None:
    MfaChallenge.objects.create(user=user, token_key="0" * 64, created_at=timezone.now())

    with pytest.raises(IntegrityError, match="user_id"), transaction.atomic():
        MfaChallenge.objects.create(user=user, token_key="1" * 64, created_at=timezone.now())


def test_two_challenges_cannot_share_a_token(user: User) -> None:
    other = User.objects.create_user("test.other@caipo.test")
    MfaChallenge.objects.create(user=user, token_key="0" * 64, created_at=timezone.now())

    with pytest.raises(IntegrityError, match="token_key"), transaction.atomic():
        MfaChallenge.objects.create(user=other, token_key="0" * 64, created_at=timezone.now())


def test_an_account_with_a_device_or_a_challenge_cannot_be_deleted(user: User) -> None:
    other = User.objects.create_user("test.other@caipo.test")
    _device(user)
    MfaChallenge.objects.create(user=other, token_key="0" * 64, created_at=timezone.now())

    for account in (user, other):
        with pytest.raises(ProtectedError):
            account.delete()

    assert User.objects.count() == 2


def test_the_device_table_holds_exactly_these_columns() -> None:
    assert {field.column for field in TotpDevice._meta.concrete_fields} == {
        "id",
        "user_id",
        "state",
        "secret_ciphertext",
        "key_id",
        "last_used_step",
        "created_at",
        "confirmed_at",
        "approved_at",
        "approved_by_id",
    }
    assert TotpDevice._meta.get_field("secret_ciphertext").get_internal_type() == "BinaryField"


def test_the_challenge_table_holds_exactly_these_columns() -> None:
    assert {field.column for field in MfaChallenge._meta.concrete_fields} == {
        "id",
        "user_id",
        "token_key",
        "created_at",
    }
