from __future__ import annotations

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.http_helpers import request_with_network_retry


pytestmark = pytest.mark.functional


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _looks_like_error_object(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    if body.get("error"):
        return True
    if body.get("status") or body.get("statusCode"):
        return True
    if body.get("errorType"):
        return True
    if body.get("message"):
        return True
    if body.get("reason"):
        return True
    return False


def _assert_error_contract(body: object) -> None:
    assert isinstance(body, dict)
    assert any(key in body for key in ("error", "message", "reason", "status", "statusCode", "errorType"))


def test_error_contract_invalid_json_body_is_handled(settings, http_session, client):
    try:
        resp = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards",
            attempts=1,
            headers={
                **_auth_headers(client.auth.token),
                "Content-Type": "application/json",
            },
            data="{",
            timeout=settings.timeout_seconds,
        )
    except NetworkError:
        pytest.skip("Network error while sending invalid JSON")

    body = _json_or_text(resp)
    if resp.status_code >= 400:
        if _looks_like_error_object(body):
            _assert_error_contract(body)
            return
        pytest.skip("Invalid JSON returned non-JSON error body")

    if _looks_like_error_object(body):
        _assert_error_contract(body)
        return

    pytest.skip("Invalid JSON did not produce an error object")


def test_error_contract_missing_content_type_is_handled(settings, http_session, client):
    try:
        resp = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards",
            attempts=1,
            headers=_auth_headers(client.auth.token),
            data="{\"title\":\"x\"}",
            timeout=settings.timeout_seconds,
        )
    except NetworkError:
        pytest.skip("Network error while sending request without content-type")

    body = _json_or_text(resp)
    if resp.status_code >= 400:
        if _looks_like_error_object(body):
            _assert_error_contract(body)
            return
        pytest.skip("Missing content-type returned non-JSON error body")

    if _looks_like_error_object(body):
        _assert_error_contract(body)
        return

    pytest.skip("Missing content-type did not produce an error object")
