import pytest

from caipo.core.correlation import correlation_scope, get_correlation_id


def test_there_is_no_correlation_id_outside_a_scope() -> None:
    assert get_correlation_id() is None


def test_a_scope_sets_a_generated_id_and_clears_it_afterwards() -> None:
    with correlation_scope() as correlation_id:
        assert len(correlation_id) == 32
        assert get_correlation_id() == correlation_id

    assert get_correlation_id() is None


def test_each_scope_gets_a_different_id() -> None:
    with correlation_scope() as first:
        pass
    with correlation_scope() as second:
        pass

    assert first != second


def test_a_scope_is_cleared_when_its_block_raises() -> None:
    with pytest.raises(RuntimeError), correlation_scope():
        raise RuntimeError

    assert get_correlation_id() is None
