import pytest


pytestmark = pytest.mark.functional


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_error_contract_has_diagnostic_fields_on_auth_failure():
    pass


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_error_contract_invalid_json_body_is_handled():
    pass


@pytest.mark.skip(reason="Planned functional tests are not implemented yet")
def test_error_contract_missing_content_type_is_handled():
    pass
