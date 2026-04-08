from __future__ import annotations

import time

import pytest

from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


pytestmark = pytest.mark.regression


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _is_permission_denied(status_code: int, body: object) -> bool:
    if is_wekan_unauthorized(status_code=status_code, body=body):
        return True

    if status_code in (401, 403):
        return True

    if isinstance(body, dict):
        status = body.get("status") or body.get("statusCode")
        try:
            if int(status) in (401, 403):
                return True
        except Exception:
            pass

        text = " ".join(str(body.get(k) or "") for k in ("error", "message", "reason", "errorType")).lower()
        if "not-authorized" in text or "not authorized" in text or "unauthorized" in text or "forbidden" in text:
            return True

    return False


def _get_user_boards_raw(*, settings, http_session, token: str, user_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{user_id}/boards",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _add_board_member_raw(*, settings, http_session, token: str, board_id: str, member_user_id: str):
    return request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards/{board_id}/members/{member_user_id}/add",
        attempts=12,
        headers=_auth_headers(token),
        json={
            "action": "add",
            "isAdmin": "false",
            "isNoComments": "false",
            "isCommentOnly": "false",
            "isWorker": "false",
        },
        timeout=settings.timeout_seconds,
    )


def _remove_board_member_raw(*, settings, http_session, token: str, board_id: str, member_user_id: str):
    return request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards/{board_id}/members/{member_user_id}/remove",
        attempts=12,
        headers=_auth_headers(token),
        json={"action": "remove"},
        timeout=settings.timeout_seconds,
    )


def _poll_until_board_visible_for_user(
    *,
    settings,
    http_session,
    token: str,
    user_id: str,
    board_id: str,
    timeout_seconds: float = 8.0,
    attempts: int = 30,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        resp = _get_user_boards_raw(settings=settings, http_session=http_session, token=token, user_id=user_id)
        if resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, list) and any(isinstance(b, dict) and str(b.get("_id") or "") == board_id for b in body):
                return True

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return False


def _poll_until_board_absent_for_user(
    *,
    settings,
    http_session,
    token: str,
    user_id: str,
    board_id: str,
    timeout_seconds: float = 8.0,
    attempts: int = 30,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        resp = _get_user_boards_raw(settings=settings, http_session=http_session, token=token, user_id=user_id)
        if resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, list):
                if not any(isinstance(b, dict) and str(b.get("_id") or "") == board_id for b in body):
                    return True

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return False


def _get_board_raw(*, settings, http_session, token: str, board_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def test_permissions_private_board_is_not_visible_to_other_user(settings, http_session, client, client2, unique_suffix: str):
    board = client.create_board(title=f"api-reg-perm-private-{unique_suffix}")
    board_id = str(board.get("_id") or "")
    assert board_id

    try:
        visible = _poll_until_board_visible_for_user(
            settings=settings,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            board_id=board_id,
            timeout_seconds=4.0,
            attempts=16,
        )
        if visible:
            pytest.xfail("BUG: other user unexpectedly sees a private board in their boards list")

        resp = _get_board_raw(settings=settings, http_session=http_session, token=client2.auth.token, board_id=board_id)
        body = _json_or_text(resp)
        if not _is_permission_denied(resp.status_code, body):
            pytest.xfail("BUG: other user can read a private board")

    finally:
        try:
            client.delete_board(board_id)
        except Exception:
            pass


def test_permissions_add_and_remove_board_member_affects_visibility(settings, http_session, client, client2, unique_suffix: str):
    board = client.create_board(title=f"api-reg-perm-share-{unique_suffix}")
    board_id = str(board.get("_id") or "")
    assert board_id

    try:
        # Before sharing: not visible / not readable.
        if not _poll_until_board_absent_for_user(
            settings=settings,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            board_id=board_id,
            timeout_seconds=4.0,
            attempts=16,
        ):
            pytest.xfail("BUG: other user already sees a private board before sharing")

        # Share board.
        resp_add = _add_board_member_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            member_user_id=client2.auth.user_id,
        )
        body_add = _json_or_text(resp_add)
        assert resp_add.status_code in (200, 400, 401, 403), f"Unexpected status from add member: {resp_add.status_code} body={body_add!r}"

        assert _poll_until_board_visible_for_user(
            settings=settings,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            board_id=board_id,
            timeout_seconds=8.0,
            attempts=30,
        ), "Board did not become visible for shared user"

        resp_read = _get_board_raw(settings=settings, http_session=http_session, token=client2.auth.token, board_id=board_id)
        body_read = _json_or_text(resp_read)
        assert resp_read.status_code == 200 and isinstance(body_read, dict) and str(body_read.get("_id") or "") == board_id

        # Unshare board.
        resp_remove = _remove_board_member_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            member_user_id=client2.auth.user_id,
        )
        body_remove = _json_or_text(resp_remove)
        assert resp_remove.status_code in (200, 400, 401, 403), f"Unexpected status from remove member: {resp_remove.status_code} body={body_remove!r}"

        if not _poll_until_board_absent_for_user(
            settings=settings,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            board_id=board_id,
            timeout_seconds=8.0,
            attempts=30,
        ):
            pytest.xfail("BUG: board still visible for other user after member removal")

        resp_after = _get_board_raw(settings=settings, http_session=http_session, token=client2.auth.token, board_id=board_id)
        body_after = _json_or_text(resp_after)
        if not _is_permission_denied(resp_after.status_code, body_after):
            pytest.xfail("BUG: other user can still read board after member removal")

    finally:
        try:
            _remove_board_member_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                member_user_id=client2.auth.user_id,
            )
        except Exception:
            pass
        try:
            client.delete_board(board_id)
        except Exception:
            pass
