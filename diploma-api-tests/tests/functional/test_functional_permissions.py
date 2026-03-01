import pytest


pytestmark = pytest.mark.functional


@pytest.mark.skip(reason="Requires two test users and optional board sharing")
def test_permissions_user_cannot_access_other_users_board():
    pass


@pytest.mark.skip(reason="Requires two test users and optional board sharing")
def test_permissions_user_cannot_modify_other_users_entities():
    pass


@pytest.mark.skip(reason="Requires two test users and optional board sharing")
def test_permissions_access_appears_after_granting_board_access():
    pass
