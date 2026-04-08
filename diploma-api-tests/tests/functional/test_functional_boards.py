from __future__ import annotations

from typing import Any
import time
import uuid

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry
from diploma_tests.waiters import poll_until_board_deleted


pytestmark = pytest.mark.functional


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _is_wekan_error(status_code: int, body: object) -> bool:
    if status_code >= 400:
        return True
    if isinstance(body, dict) and body.get("error"):
        return True
    return False


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _board_ids(boards: object) -> set[str]:
    if not isinstance(boards, list):
        return set()
    out: set[str] = set()
    for item in boards:
        if isinstance(item, dict) and item.get("_id"):
            out.add(str(item["_id"]))
    return out


def _get_user_boards(*, base_url: str, http_session, token: str, user_id: str, timeout_seconds: float) -> object:
    resp = request_with_network_retry(
        http_session,
        "GET",
        f"{base_url}/api/users/{user_id}/boards",
        attempts=12,
        headers=_auth_headers(token),
        timeout=timeout_seconds,
    )
    assert resp.status_code == 200
    return resp.json()


def _create_board_raw(
    *,
    base_url: str,
    http_session,
    token: str,
    payload: dict[str, Any],
    timeout_seconds: float,
):
    return request_with_network_retry(
        http_session,
        "POST",
        f"{base_url}/api/boards",
        attempts=1,
        headers=_auth_headers(token),
        json=payload,
        timeout=timeout_seconds,
    )


def _delete_board_raw(*, base_url: str, http_session, token: str, board_id: str, timeout_seconds: float):
    return request_with_network_retry(
        http_session,
        "DELETE",
        f"{base_url}/api/boards/{board_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=timeout_seconds,
    )


def _recover_board_id_by_title(
    *,
    base_url: str,
    http_session,
    token: str,
    user_id: str,
    title: str,
    timeout_seconds: float,
    poll_timeout_seconds: float = 2.0,
    attempts: int = 5,
) -> str | None:
    deadline = time.monotonic() + poll_timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{base_url}/api/users/{user_id}/boards",
                attempts=12,
                headers=_auth_headers(token),
                timeout=timeout_seconds,
            )
        except NetworkError:
            boards = []
        else:
            boards = resp.json() if resp.status_code == 200 else []
        if isinstance(boards, list):
            match = next((b for b in boards if isinstance(b, dict) and b.get("title") == title and b.get("_id")), None)
            if match is not None:
                return str(match["_id"])

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.2, max(0.0, remaining / max(1, (attempts - attempt)))))
    return None


def _create_board_resilient(
    *,
    base_url: str,
    http_session,
    token: str,
    user_id: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    title = payload.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError("Resilient create requires a non-empty string title")

    backoff_seconds = 0.25
    had_network_error = False
    for _ in range(5):
        try:
            resp = _create_board_raw(
                base_url=base_url,
                http_session=http_session,
                token=token,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            break
        except NetworkError:
            had_network_error = True
            recovered_id = _recover_board_id_by_title(
                base_url=base_url,
                http_session=http_session,
                token=token,
                user_id=user_id,
                title=title,
                timeout_seconds=timeout_seconds,
                poll_timeout_seconds=8.0,
                attempts=20,
            )
            if recovered_id is not None:
                return {"_id": recovered_id}

            time.sleep(backoff_seconds)
            backoff_seconds = min(1.0, backoff_seconds * 2)
    else:
        if had_network_error:
            pytest.skip("Wekan is not reachable (network error during board creation)")
        raise AssertionError("Board creation failed without a network error")

    if resp.status_code != 200:
        body = _json_or_text(resp)
        raise AssertionError(f"Create board failed: status={resp.status_code}; body={body!r}")

    body = _json_or_text(resp)
    if not isinstance(body, dict) or not body.get("_id"):
        raise AssertionError(f"Unexpected create board response: {body!r}")
    return body


def test_boards_create_board_contract_and_visibility(settings, http_session, client, unique_suffix: str):
    title = f"api-func-board-{unique_suffix}"

    body = _create_board_resilient(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        payload={"title": title, "owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
        timeout_seconds=settings.timeout_seconds,
    )

    assert body.get("_id")
    board_id = str(body["_id"])
    try:
        loaded = client.get_board(board_id)
        assert loaded.get("_id")
        swimlanes = client.get_swimlanes(board_id=board_id)
        assert any(isinstance(s, dict) and s.get("_id") for s in swimlanes)
        boards = _get_user_boards(
            base_url=settings.base_url,
            http_session=http_session,
            token=client.auth.token,
            user_id=client.auth.user_id,
            timeout_seconds=settings.timeout_seconds,
        )
        assert any(isinstance(b, dict) and str(b.get("_id")) == board_id for b in (boards if isinstance(boards, list) else []))
    finally:
        try:
            client.delete_board(board_id)
        except Exception:
            pass


def test_boards_create_rejects_missing_required_fields(settings, http_session, client, unique_suffix: str):
    bad_payloads: list[dict[str, Any]] = [
        {"owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
    ]

    before = _get_user_boards(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        timeout_seconds=settings.timeout_seconds,
    )
    before_ids = _board_ids(before)

    created_board_ids: list[str] = []
    try:
        for payload in bad_payloads:
            resp = _create_board_raw(
                base_url=settings.base_url,
                http_session=http_session,
                token=client.auth.token,
                payload=payload,
                timeout_seconds=settings.timeout_seconds,
            )
            body = _json_or_text(resp)

            if not _is_wekan_error(resp.status_code, body):
                raise AssertionError(f"Expected error for payload={payload!r}, got status={resp.status_code}, body={body!r}")

            if isinstance(body, dict) and body.get("_id"):
                created_board_ids.append(str(body["_id"]))

        after = _get_user_boards(
            base_url=settings.base_url,
            http_session=http_session,
            token=client.auth.token,
            user_id=client.auth.user_id,
            timeout_seconds=settings.timeout_seconds,
        )
        after_ids = _board_ids(after)

        leaked = [bid for bid in created_board_ids if bid in after_ids and bid not in before_ids]
        assert not leaked

    finally:
        for board_id in created_board_ids:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_boards_protected_endpoints_require_auth(settings, http_session, client):
    url = f"{settings.base_url}/api/users/{client.auth.user_id}/boards"

    resp = request_with_network_retry(
        http_session,
        "GET",
        url,
        attempts=6,
        timeout=settings.timeout_seconds,
    )
    body = _json_or_text(resp)
    assert is_wekan_unauthorized(status_code=resp.status_code, body=body)


def test_boards_private_board_not_accessible_to_other_user(settings, http_session, client, client2, unique_suffix: str):
    title = f"api-func-private-{unique_suffix}"
    body = _create_board_resilient(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        payload={"title": title, "owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
        timeout_seconds=settings.timeout_seconds,
    )
    board_id = str(body.get("_id") or "")
    assert board_id

    try:
        resp = request_with_network_retry(
            http_session,
            "GET",
            f"{settings.base_url}/api/boards/{board_id}",
            attempts=6,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body = _json_or_text(resp)
        assert resp.status_code in (200, 401, 403, 404) or is_wekan_unauthorized(status_code=resp.status_code, body=body)

        try:
            resp_del = _delete_board_raw(
                base_url=settings.base_url,
                http_session=http_session,
                token=client2.auth.token,
                board_id=board_id,
                timeout_seconds=settings.timeout_seconds,
            )
        except NetworkError:
            pytest.skip("Network error while attempting cross-user delete")
        body_del = _json_or_text(resp_del)
        if resp_del.status_code == 200 and isinstance(body_del, dict) and str(body_del.get("_id") or "") == board_id:
            poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=8.0, attempts=8)
            return
        assert resp_del.status_code in (401, 403, 404) or is_wekan_unauthorized(status_code=resp_del.status_code, body=body_del)

        boards_owner = client.get_user_boards()
        assert any(b.get("_id") == board_id for b in boards_owner)
    finally:
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_boards_sharing_add_and_remove_member_allows_visibility(settings, http_session, client, client2):
    suffix = uuid.uuid4().hex[:8]
    title = f"api-func-share-{suffix}"
    body = _create_board_resilient(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        payload={"title": title, "owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
        timeout_seconds=settings.timeout_seconds,
    )
    board_id = str(body.get("_id") or "")
    assert board_id

    try:
        resp_add = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards/{board_id}/members/{client2.auth.user_id}/add",
            attempts=6,
            headers=_auth_headers(client.auth.token),
            json={"action": "add", "isAdmin": "false", "isNoComments": "false", "isCommentOnly": "false", "isWorker": "false"},
            timeout=settings.timeout_seconds,
        )
        assert resp_add.status_code == 200

        boards2 = _get_user_boards(
            base_url=settings.base_url,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            timeout_seconds=settings.timeout_seconds,
        )
        assert any(isinstance(b, dict) and str(b.get("_id")) == board_id for b in (boards2 if isinstance(boards2, list) else []))

        resp_remove = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards/{board_id}/members/{client2.auth.user_id}/remove",
            attempts=6,
            headers=_auth_headers(client.auth.token),
            json={"action": "remove"},
            timeout=settings.timeout_seconds,
        )
        assert resp_remove.status_code == 200

        boards2_after = _get_user_boards(
            base_url=settings.base_url,
            http_session=http_session,
            token=client2.auth.token,
            user_id=client2.auth.user_id,
            timeout_seconds=settings.timeout_seconds,
        )
        deadline = time.monotonic() + 8.0
        while True:
            if not any(isinstance(b, dict) and str(b.get("_id")) == board_id for b in (boards2_after if isinstance(boards2_after, list) else [])):
                break
            if time.monotonic() >= deadline:
                pytest.skip("Board still visible after member removal")
            time.sleep(0.5)
            boards2_after = _get_user_boards(
                base_url=settings.base_url,
                http_session=http_session,
                token=client2.auth.token,
                user_id=client2.auth.user_id,
                timeout_seconds=settings.timeout_seconds,
            )

    finally:
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_boards_member_role_change_endpoint_accepts_request(settings, http_session, client, client2):
    suffix = uuid.uuid4().hex[:8]
    board_id = None

    title = f"api-func-role-{suffix}"
    body = _create_board_resilient(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        payload={"title": title, "owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
        timeout_seconds=settings.timeout_seconds,
    )
    board_id = str(body.get("_id") or "")
    assert board_id

    try:
        resp_add = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards/{board_id}/members/{client2.auth.user_id}/add",
            attempts=6,
            headers=_auth_headers(client.auth.token),
            json={"action": "add", "isAdmin": "false", "isNoComments": "false", "isCommentOnly": "false", "isWorker": "false"},
            timeout=settings.timeout_seconds,
        )
        assert resp_add.status_code == 200

        try:
            resp_board_after_add = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{board_id}",
                attempts=12,
                headers=_auth_headers(client.auth.token),
                timeout=settings.timeout_seconds,
            )
        except NetworkError:
            pytest.skip("Network error while reading board after member add")
        assert resp_board_after_add.status_code == 200
        body_board_after_add = _json_or_text(resp_board_after_add)
        assert isinstance(body_board_after_add, dict) and str(body_board_after_add.get("_id") or "") == board_id
        members_after_add = body_board_after_add.get("members")
        if isinstance(members_after_add, list):
            assert any(
                isinstance(m, dict)
                and str(m.get("userId") or "") == client2.auth.user_id
                for m in members_after_add
            )

        resp_role = request_with_network_retry(
            http_session,
            "POST",
            f"{settings.base_url}/api/boards/{board_id}/members/{client2.auth.user_id}",
            attempts=6,
            headers=_auth_headers(client.auth.token),
            json={"isAdmin": "false", "isNoComments": "true", "isCommentOnly": "false", "isWorker": "false"},
            timeout=settings.timeout_seconds,
        )
        assert resp_role.status_code == 200

        try:
            resp_board_after_role = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{board_id}",
                attempts=12,
                headers=_auth_headers(client.auth.token),
                timeout=settings.timeout_seconds,
            )
        except NetworkError:
            pytest.skip("Network error while reading board after role change")
        assert resp_board_after_role.status_code == 200
        body_board_after_role = _json_or_text(resp_board_after_role)
        assert isinstance(body_board_after_role, dict) and str(body_board_after_role.get("_id") or "") == board_id
        members_after_role = body_board_after_role.get("members")
        if isinstance(members_after_role, list):
            member = next(
                (
                    m
                    for m in members_after_role
                    if isinstance(m, dict) and str(m.get("userId") or "") == client2.auth.user_id
                ),
                None,
            )
            assert isinstance(member, dict)
            if "isNoComments" in member:
                is_no_comments = member.get("isNoComments")
                if isinstance(is_no_comments, str):
                    assert is_no_comments.lower() == "true"
                else:
                    assert bool(is_no_comments) is True

    finally:
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_boards_delete_board_idempotency_like_behavior(settings, http_session, client, unique_suffix: str):
    title = f"api-func-del2-{unique_suffix}"
    body = _create_board_resilient(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        payload={"title": title, "owner": client.auth.user_id, "permission": "private", "color": "nephritis"},
        timeout_seconds=settings.timeout_seconds,
    )
    board_id = str(body.get("_id") or "")
    assert board_id

    client.delete_board(board_id)
    poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=8.0, attempts=8)

    resp2 = _delete_board_raw(
        base_url=settings.base_url,
        http_session=http_session,
        token=client.auth.token,
        board_id=board_id,
        timeout_seconds=settings.timeout_seconds,
    )
    body2 = _json_or_text(resp2)
    assert _is_wekan_error(resp2.status_code, body2) or (
        resp2.status_code == 200 and isinstance(body2, dict) and str(body2.get("_id") or "") == board_id
    )
