from __future__ import annotations

import pytest

from diploma_tests.config import Settings
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


def _build_login_payload(settings: Settings, *, password: object) -> dict[str, object]:
    payload: dict[str, object] = {"password": password}
    if settings.username:
        payload["username"] = settings.username
    elif settings.email:
        payload["email"] = settings.email
    else:
        pytest.skip("No WEKAN_USERNAME/WEKAN_EMAIL configured")
    return payload


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _assert_no_token(body: object) -> None:
    if isinstance(body, dict) and body.get("token"):
        raise AssertionError("Token unexpectedly present in a negative login scenario")


@pytest.mark.regression
def test_login_rejects_invalid_password(settings: Settings, http_session):
    payload = _build_login_payload(settings, password="definitely-wrong")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    _assert_no_token(body)

    assert resp.status_code in (400, 401, 403), f"Unexpected status for invalid password: {resp.status_code}"


@pytest.mark.regression
def test_login_rejects_empty_password(settings: Settings, http_session):
    payload = _build_login_payload(settings, password="")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    _assert_no_token(body)
    assert resp.status_code in (400, 401, 403), f"Unexpected status for empty password: {resp.status_code}"


@pytest.mark.regression
def test_login_rejects_missing_password_field(settings: Settings, http_session):
    payload = _build_login_payload(settings, password="irrelevant")
    payload.pop("password", None)

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json=payload,
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    _assert_no_token(body)
    assert resp.status_code in (400, 401, 403), f"Unexpected status for missing password: {resp.status_code}"


@pytest.mark.regression
def test_login_rejects_missing_username_and_email(settings: Settings, http_session):
    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=6,
        json={"password": "anything"},
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    _assert_no_token(body)
    assert resp.status_code in (400, 401, 403), f"Unexpected status for missing user identifier: {resp.status_code}"


@pytest.mark.regression
def test_api_requires_auth_for_board_create(settings: Settings, http_session):
    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards",
        attempts=6,
        json={"title": "unauth-board", "owner": "nope", "permission": "private", "color": "nephritis"},
        timeout=settings.timeout_seconds,
    )
    body = _json_or_text(resp)
    assert is_wekan_unauthorized(status_code=resp.status_code, body=body), "Expected unauthorized response"


@pytest.mark.regression
def test_api_requires_auth_for_get_user_boards(settings: Settings, http_session, client):
    resp = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{client.auth.user_id}/boards",
        attempts=6,
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    assert is_wekan_unauthorized(status_code=resp.status_code, body=body), "Expected unauthorized response"


@pytest.mark.regression
def test_api_rejects_invalid_token_for_get_user_boards(settings: Settings, http_session, client):
    resp = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{client.auth.user_id}/boards",
        attempts=6,
        headers={"Authorization": "Bearer definitely-invalid"},
        timeout=settings.timeout_seconds,
    )

    body = _json_or_text(resp)
    assert is_wekan_unauthorized(status_code=resp.status_code, body=body), "Expected unauthorized response"
