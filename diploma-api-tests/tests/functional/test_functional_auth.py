from __future__ import annotations

from typing import Any

import pytest

from diploma_tests.config import Settings
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


pytestmark = pytest.mark.functional


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _redacted(body: object) -> object:
    if not isinstance(body, dict):
        return body
    copied = dict(body)
    if "token" in copied:
        copied["token"] = "<redacted>"
    return copied


def _build_login_payload(settings: Settings, *, password: Any, prefer: str = "auto") -> dict[str, Any]:
    payload: dict[str, Any] = {"password": password}

    if prefer == "username":
        if not settings.username:
            pytest.skip("WEKAN_USERNAME is not configured")
        payload["username"] = settings.username
        return payload

    if prefer == "email":
        if not settings.email:
            pytest.skip("WEKAN_EMAIL is not configured")
        payload["email"] = settings.email
        return payload

    if settings.username:
        payload["username"] = settings.username
    elif settings.email:
        payload["email"] = settings.email
    else:
        pytest.skip("No WEKAN_USERNAME/WEKAN_EMAIL configured")

    return payload


def _assert_login_rejected(resp) -> None:
    body = _json_or_text(resp)
    if isinstance(body, dict) and body.get("token"):
        raise AssertionError(f"Token unexpectedly present in a negative login scenario: {_redacted(body)}")

    assert resp.status_code in (400, 401, 403), f"Unexpected status for rejected login: {resp.status_code}; body={_redacted(body)}"


def _assert_login_success(resp) -> tuple[str, str]:
    body = _json_or_text(resp)
    if resp.status_code != 200:
        raise AssertionError(
            "Unexpected status for successful login: "
            f"{resp.status_code}; body={_redacted(body)}"
        )
    assert isinstance(body, dict), f"Unexpected login response type: {type(body).__name__}"
    assert body.get("token"), "Login response has no token"
    assert body.get("id"), "Login response has no id"
    return str(body["token"]), str(body["id"])


@pytest.mark.parametrize("prefer", ["auto", "username", "email"])
def test_login_success_returns_token_and_id(settings: Settings, http_session, prefer: str):
    payload = _build_login_payload(settings, password=settings.password or "", prefer=prefer)

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=8,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    token, user_id = _assert_login_success(resp)
    resp2 = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{user_id}/boards",
        attempts=6,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.timeout_seconds,
    )
    assert resp2.status_code == 200, f"Token did not work for protected endpoint: {resp2.status_code}"
    assert isinstance(resp2.json(), list)


def test_login_rejects_invalid_password_no_token(settings: Settings, http_session):
    payload = _build_login_payload(settings, password="definitely-wrong")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    _assert_login_rejected(resp)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"password": "x"},
        {"username": "", "password": "x"},
        {"email": "", "password": "x"},
        {"username": None, "password": "x"},
        {"email": None, "password": "x"},
        {"password": ""},
    ],
)
def test_login_rejects_missing_or_empty_credentials_fields(settings: Settings, http_session, payload: dict[str, Any]):
    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    _assert_login_rejected(resp)


@pytest.mark.parametrize(
    "password",
    [
        123,
        True,
        [],
        {"oops": "nope"},
    ],
)
def test_login_rejects_non_string_password(settings: Settings, http_session, password: Any):
    payload = _build_login_payload(settings, password=password)

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    _assert_login_rejected(resp)


@pytest.mark.parametrize(
    "header_value",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Bearer definitely-invalid",
        "Token definitely-invalid",
        "definitely-invalid",
    ],
)
def test_protected_endpoint_rejects_missing_or_invalid_token(settings: Settings, http_session, client, header_value: str | None):
    url = f"{settings.base_url}/api/users/{client.auth.user_id}/boards"
    headers: dict[str, str] | None
    if header_value is None:
        headers = None
    else:
        headers = {"Authorization": header_value}

    resp = request_with_network_retry(
        http_session,
        "GET",
        url,
        attempts=6,
        headers=headers,
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    assert is_wekan_unauthorized(status_code=resp.status_code, body=body), f"Expected unauthorized; status={resp.status_code}; body={_redacted(body)}"


def test_login_second_user_success_token_works_when_configured(settings: Settings, http_session):
    if not settings.has_second_login_credentials:
        pytest.skip("Second test user is not configured")

    payload: dict[str, Any] = {"password": settings.password2 or ""}
    if settings.username2:
        payload["username"] = settings.username2
    elif settings.email2:
        payload["email"] = settings.email2
    else:
        pytest.skip("Second user identifier is not configured")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=8,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    if resp.status_code != 200:
        body = _json_or_text(resp)
        if isinstance(body, dict) and body.get("error") == "not-found":
            pytest.skip(
                "Second test user is configured in .env but does not exist on the Wekan server. "
                "Create this user in Wekan UI (or enable /users/register) and re-run. "
                f"Server says: {_redacted(body)}"
            )

    token, user_id = _assert_login_success(resp)

    resp2 = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{user_id}/boards",
        attempts=6,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.timeout_seconds,
    )

    assert resp2.status_code == 200, f"Second user's token did not work: {resp2.status_code}"
    assert isinstance(resp2.json(), list)
