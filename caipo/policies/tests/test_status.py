"""The derived formal status of a policy (DATA_MODEL.md §4.4)."""

from datetime import date

import pytest

from caipo.policies.status import FormalStatus, derive_status

D1, D2, D3 = date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([], FormalStatus.UNKNOWN),
        ([("amended", D1)], FormalStatus.UNKNOWN),
        ([("adopted", D1)], FormalStatus.ADOPTED_NOT_IN_FORCE),
        ([("adopted", D1), ("amended", D2)], FormalStatus.ADOPTED_NOT_IN_FORCE),
        ([("adopted", D1), ("entered_into_force", D2)], FormalStatus.IN_FORCE),
        ([("entered_into_force", D2), ("amended", D3)], FormalStatus.IN_FORCE),
        ([("adopted", D1), ("entered_into_force", D2), ("expired", D3)], FormalStatus.EXPIRED),
        ([("adopted", D1), ("entered_into_force", D2), ("repealed", D3)], FormalStatus.REPEALED),
        ([("repealed", D1), ("expired", D2)], FormalStatus.REPEALED),
    ],
)
def test_status_follows_the_table(events: list[tuple[str, date]], expected: FormalStatus) -> None:
    assert derive_status(events) is expected


def test_events_after_the_date_asked_about_do_not_count() -> None:
    events = [("adopted", D1), ("entered_into_force", D2), ("repealed", D3)]

    assert derive_status(events, on=D1) is FormalStatus.ADOPTED_NOT_IN_FORCE
    assert derive_status(events, on=D2) is FormalStatus.IN_FORCE
    assert derive_status(events, on=D3) is FormalStatus.REPEALED


def test_a_policy_has_no_stored_status() -> None:
    from caipo.policies.models import Policy

    names = {field.name for field in Policy._meta.get_fields()}
    assert not {"status", "formal_status", "state"} & names
