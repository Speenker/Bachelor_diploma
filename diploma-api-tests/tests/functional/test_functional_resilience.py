import pytest


pytestmark = [pytest.mark.functional, pytest.mark.slow]


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_resilience_repeated_delete_is_handled_predictably():
    pass


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_resilience_handles_transient_network_errors():
    pass


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_resilience_suite_is_order_independent():
    pass
