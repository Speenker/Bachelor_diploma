from __future__ import annotations

import pytest

from diploma_tests.config import Settings
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


@pytest.mark.regression
def test_login_rejects_invalid_password(settings: Settings, http_session):
    # We intentionally call the endpoint directly to assert status code
    # (the high-level client raises on non-2xx).
    payload: dict[str, str] = {"password": "definitely-wrong"}
    if settings.username:
        payload["username"] = settings.username
    elif settings.email:
        payload["email"] = settings.email
    else:
        pytest.skip("No username/email configured")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    # Wekan returns HTTP 400 for incorrect password (with a JSON body containing error=403).
    assert resp.status_code in (400, 401, 403), resp.text


@pytest.mark.regression
def test_api_requires_auth_for_board_create(settings: Settings, http_session):
    # No Authorization header.
    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards",
        attempts=6,
        json={"title": "unauth-board", "owner": "nope", "permission": "private", "color": "nephritis"},
        timeout=settings.timeout_seconds,
    )

    # Wekan can respond with HTTP 401/403 or with HTTP 200 and an error object in JSON.
    body: object
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    assert is_wekan_unauthorized(status_code=resp.status_code, body=body), resp.text
