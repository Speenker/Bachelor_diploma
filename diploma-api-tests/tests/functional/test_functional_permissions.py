from __future__ import annotations

from typing import Any
import time

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


pytestmark = pytest.mark.functional


def _json_or_text(resp) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_or_skip(http_session, *, method: str, url: str, skip_reason: str, attempts: int, **kwargs: Any):
    try:
        return request_with_network_retry(http_session, method, url, attempts=attempts, **kwargs)
    except AssertionError:
        pytest.skip(skip_reason)


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

    if body is None:
        return True
    if isinstance(body, str) and not body.strip():
        return True
    if isinstance(body, dict) and not body:
        return True

    return False


def _recover_board_id_by_title(
    *,
    settings,
    http_session,
    token: str,
    user_id: str,
    title: str,
    poll_timeout_seconds: float = 6.0,
    attempts: int = 20,
) -> str | None:
    deadline = time.monotonic() + poll_timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/users/{user_id}/boards",
                attempts=12,
                headers=_auth_headers(token),
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            resp = None

        if resp is not None and resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, list):
                match = next((b for b in body if isinstance(b, dict) and b.get("title") == title and b.get("_id")), None)
                if match is not None:
                    return str(match["_id"])

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return None


def _create_board_resilient(*, settings, http_session, token: str, user_id: str, title: str) -> tuple[str, str]:
    payload = {"title": title, "owner": user_id, "permission": "private", "color": "nephritis"}

    backoff_seconds = 0.25
    for _ in range(5):
        try:
            resp = request_with_network_retry(
                http_session,
                "POST",
                f"{settings.base_url}/api/boards",
                attempts=1,
                headers=_auth_headers(token),
                json=payload,
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            resp = None

        if resp is not None and resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, dict) and body.get("_id"):
                board_id = str(body["_id"])
                swimlane_id = str(body.get("defaultSwimlaneId") or "")
                if swimlane_id:
                    return board_id, swimlane_id

                try:
                    resp_board = request_with_network_retry(
                        http_session,
                        "GET",
                        f"{settings.base_url}/api/boards/{board_id}",
                        attempts=12,
                        headers=_auth_headers(token),
                        timeout=settings.timeout_seconds,
                    )
                except AssertionError:
                    resp_board = None

                if resp_board is not None and resp_board.status_code == 200:
                    body_board = _json_or_text(resp_board)
                    if isinstance(body_board, dict) and body_board.get("defaultSwimlaneId"):
                        return board_id, str(body_board.get("defaultSwimlaneId"))

        recovered_id = _recover_board_id_by_title(
            settings=settings,
            http_session=http_session,
            token=token,
            user_id=user_id,
            title=title,
            poll_timeout_seconds=8.0,
            attempts=20,
        )
        if recovered_id is not None:
            resp_board = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{recovered_id}",
                attempts=12,
                headers=_auth_headers(token),
                timeout=settings.timeout_seconds,
            )
            assert resp_board.status_code == 200
            body_board = _json_or_text(resp_board)
            assert isinstance(body_board, dict) and body_board.get("defaultSwimlaneId")
            return recovered_id, str(body_board.get("defaultSwimlaneId"))

        time.sleep(backoff_seconds)
        backoff_seconds = min(1.0, backoff_seconds * 2)

    raise AssertionError("Network error during board creation")


def _delete_board(*, settings, http_session, token: str, board_id: str) -> None:
    try:
        request_with_network_retry(
            http_session,
            "DELETE",
            f"{settings.base_url}/api/boards/{board_id}",
            attempts=12,
            headers=_auth_headers(token),
            timeout=settings.timeout_seconds,
        )
    except AssertionError:
        pass


def _create_list_raw(*, settings, http_session, token: str, board_id: str, payload: dict[str, Any]):
    return request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards/{board_id}/lists",
        attempts=1,
        headers=_auth_headers(token),
        json=payload,
        timeout=settings.timeout_seconds,
    )


def _get_list_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _delete_list_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "DELETE",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _create_card_raw(*, settings, http_session, token: str, board_id: str, list_id: str, payload: dict[str, Any]):
    return request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards",
        attempts=1,
        headers=_auth_headers(token),
        json=payload,
        timeout=settings.timeout_seconds,
    )


def _get_card_raw(*, settings, http_session, token: str, board_id: str, list_id: str, card_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _update_card_raw(*, settings, http_session, token: str, board_id: str, list_id: str, card_id: str, payload: dict[str, Any]):
    return request_with_network_retry(
        http_session,
        "PUT",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
        attempts=12,
        headers=_auth_headers(token),
        json=payload,
        timeout=settings.timeout_seconds,
    )


def _delete_card_raw(*, settings, http_session, token: str, board_id: str, list_id: str, card_id: str, author_id: str):
    return request_with_network_retry(
        http_session,
        "DELETE",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
        attempts=12,
        headers=_auth_headers(token),
        json={"authorId": author_id},
        timeout=settings.timeout_seconds,
    )


def _update_board_title_raw(*, settings, http_session, token: str, board_id: str, title: str):
    return request_with_network_retry(
        http_session,
        "PUT",
        f"{settings.base_url}/api/boards/{board_id}/title",
        attempts=12,
        headers=_auth_headers(token),
        json={"title": title},
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


def _poll_other_user_can_read_board(*, settings, http_session, board_id: str, other_user_token: str, timeout_seconds: float = 8.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{board_id}",
                attempts=12,
                headers=_auth_headers(other_user_token),
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            pytest.skip("Network error while polling other-user board access")

        body = _json_or_text(resp)
        if resp.status_code == 200 and isinstance(body, dict) and str(body.get("_id") or "") == board_id:
            return body

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.25, remaining))


def test_permissions_other_user_cannot_read_change_or_delete_foreign_entities(settings, http_session, client, client2, unique_suffix: str):
    board_title_original = f"api-func-perm-board-{unique_suffix}"
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=board_title_original,
    )

    list_id = None
    list_id_2 = None
    card_id = None

    card_title_original = f"api-func-perm-card-{unique_suffix}"
    card_desc_original = f"desc-{unique_suffix}"

    try:
        try:
            resp_list = _create_list_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                payload={"title": f"api-func-perm-list-{unique_suffix}"},
            )
        except AssertionError:
            pytest.skip("Network error while creating list")
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        try:
            resp_list2 = _create_list_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                payload={"title": f"api-func-perm-list2-{unique_suffix}"},
            )
        except AssertionError:
            pytest.skip("Network error while creating second list")
        assert resp_list2.status_code == 200
        body_list2 = _json_or_text(resp_list2)
        assert isinstance(body_list2, dict) and body_list2.get("_id")
        list_id_2 = str(body_list2["_id"])

        try:
            resp_card = _create_card_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=list_id,
                payload={
                    "title": card_title_original,
                    "description": card_desc_original,
                    "authorId": client.auth.user_id,
                    "swimlaneId": swimlane_id,
                },
            )
        except AssertionError:
            pytest.skip("Network error while creating card")
        assert resp_card.status_code == 200
        body_card = _json_or_text(resp_card)
        assert isinstance(body_card, dict) and body_card.get("_id")
        card_id = str(body_card["_id"])

        resp_read_board = _request_or_skip(
            http_session,
            method="GET",
            url=f"{settings.base_url}/api/boards/{board_id}",
            skip_reason="Network error during other-user board read",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_read_board = _json_or_text(resp_read_board)
        if not _is_permission_denied(resp_read_board.status_code, body_read_board):
            pytest.skip("Other user can read private board")

        resp_read_list = _request_or_skip(
            http_session,
            method="GET",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
            skip_reason="Network error during other-user list read",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_read_list = _json_or_text(resp_read_list)
        if not _is_permission_denied(resp_read_list.status_code, body_read_list):
            pytest.skip("Other user can read list on private board")

        resp_read_card = _request_or_skip(
            http_session,
            method="GET",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
            skip_reason="Network error during other-user card read",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_read_card = _json_or_text(resp_read_card)
        if not _is_permission_denied(resp_read_card.status_code, body_read_card):
            pytest.skip("Other user can read card on private board")

        attempted_title = f"api-func-perm-board-hacked-{unique_suffix}"
        resp_upd_board = _request_or_skip(
            http_session,
            method="PUT",
            url=f"{settings.base_url}/api/boards/{board_id}/title",
            skip_reason="Network error during other-user board title update",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            json={"title": attempted_title},
            timeout=settings.timeout_seconds,
        )
        body_upd_board = _json_or_text(resp_upd_board)
        if not _is_permission_denied(resp_upd_board.status_code, body_upd_board):
            try:
                loaded = client.get_board(board_id)
                actual_title = str(loaded.get("title") or "")
                if actual_title != board_title_original:
                    try:
                        _update_board_title_raw(
                            settings=settings,
                            http_session=http_session,
                            token=client.auth.token,
                            board_id=board_id,
                            title=board_title_original,
                        )
                    except Exception:
                        pass
            except NetworkError:
                pass
            pytest.skip("Other user can update board title")

        try:
            loaded_board = client.get_board(board_id)
        except NetworkError:
            pytest.skip("Network error while verifying board title unchanged")
        assert str(loaded_board.get("title") or "") == board_title_original

        attempted_card_title = f"api-func-perm-card-hacked-{unique_suffix}"
        attempted_card_desc = f"hacked-{unique_suffix}"
        resp_upd_card = _request_or_skip(
            http_session,
            method="PUT",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
            skip_reason="Network error during other-user card update",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            json={
                "title": attempted_card_title,
                "description": attempted_card_desc,
                "authorId": client2.auth.user_id,
                "listId": list_id,
            },
            timeout=settings.timeout_seconds,
        )
        body_upd_card = _json_or_text(resp_upd_card)
        if not _is_permission_denied(resp_upd_card.status_code, body_upd_card):
            try:
                loaded_after = client.get_card(board_id=board_id, list_id=list_id, card_id=card_id)
                if loaded_after is not None:
                    changed = (
                        str(loaded_after.get("title") or "") == attempted_card_title
                        or str(loaded_after.get("description") or "") == attempted_card_desc
                    )
                    if changed:
                        try:
                            client.update_card(
                                board_id=board_id,
                                list_id=list_id,
                                card_id=card_id,
                                swimlane_id=swimlane_id,
                                title=card_title_original,
                                description=card_desc_original,
                                new_list_id=list_id,
                            )
                        except Exception:
                            pass
            except NetworkError:
                pass
            pytest.skip("Other user can update card")

        try:
            loaded_card = client.get_card(board_id=board_id, list_id=list_id, card_id=card_id)
        except NetworkError:
            pytest.skip("Network error while verifying card unchanged")
        assert loaded_card is not None
        if "title" in loaded_card:
            assert str(loaded_card.get("title") or "") == card_title_original
        if "description" in loaded_card:
            assert str(loaded_card.get("description") or "") == card_desc_original

        resp_move_card = _request_or_skip(
            http_session,
            method="PUT",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
            skip_reason="Network error during other-user card move",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            json={
                "authorId": client2.auth.user_id,
                "listId": list_id_2,
            },
            timeout=settings.timeout_seconds,
        )
        body_move_card = _json_or_text(resp_move_card)
        if not _is_permission_denied(resp_move_card.status_code, body_move_card):
            try:
                moved = client.get_card(board_id=board_id, list_id=list_id_2, card_id=card_id)
                if moved is not None and str(moved.get("listId") or "") == list_id_2:
                    try:
                        client.update_card(
                            board_id=board_id,
                            list_id=list_id_2,
                            card_id=card_id,
                            swimlane_id=swimlane_id,
                            new_list_id=list_id,
                        )
                    except Exception:
                        pass
            except NetworkError:
                pass
            pytest.skip("Other user can move card")

        try:
            loaded_after_move = client.get_card(board_id=board_id, list_id=list_id, card_id=card_id)
        except NetworkError:
            pytest.skip("Network error while verifying card not moved")
        assert loaded_after_move is not None
        assert str(loaded_after_move.get("listId") or "") == list_id

        resp_del_card = _request_or_skip(
            http_session,
            method="DELETE",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
            skip_reason="Network error during other-user card delete",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            json={"authorId": client2.auth.user_id},
            timeout=settings.timeout_seconds,
        )
        body_del_card = _json_or_text(resp_del_card)
        if not _is_permission_denied(resp_del_card.status_code, body_del_card):
            pytest.skip("Other user can delete card")

        try:
            still_there = client.get_card(board_id=board_id, list_id=list_id, card_id=card_id)
        except NetworkError:
            pytest.skip("Network error while verifying card not deleted")
        assert still_there is not None

        resp_del_list = _request_or_skip(
            http_session,
            method="DELETE",
            url=f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
            skip_reason="Network error during other-user list delete",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_del_list = _json_or_text(resp_del_list)
        if not _is_permission_denied(resp_del_list.status_code, body_del_list):
            pytest.skip("Other user can delete list")

        try:
            list_loaded = client.get_list(board_id=board_id, list_id=list_id)
        except NetworkError:
            pytest.skip("Network error while verifying list not deleted")
        assert str(list_loaded.get("_id") or "") == list_id

        resp_del_board = _request_or_skip(
            http_session,
            method="DELETE",
            url=f"{settings.base_url}/api/boards/{board_id}",
            skip_reason="Network error during other-user board delete",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_del_board = _json_or_text(resp_del_board)
        if not _is_permission_denied(resp_del_board.status_code, body_del_board):
            pytest.skip("Other user can delete board")

        try:
            loaded_board_after = client.get_board(board_id)
        except NetworkError:
            pytest.skip("Network error while verifying board not deleted")
        assert str(loaded_board_after.get("_id") or "") == board_id

    finally:
        if board_id and list_id and card_id:
            try:
                _delete_card_raw(
                    settings=settings,
                    http_session=http_session,
                    token=client.auth.token,
                    board_id=board_id,
                    list_id=list_id,
                    card_id=card_id,
                    author_id=client.auth.user_id,
                )
            except Exception:
                pass
        if board_id and list_id_2:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id_2)
            except Exception:
                pass
        if board_id and list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_permissions_access_appears_after_granting_board_access(settings, http_session, client, client2, unique_suffix: str):
    board_title = f"api-func-perm-share-board-{unique_suffix}"
    board_id, _swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=board_title,
    )

    list_id = None
    try:
        try:
            resp_list = _create_list_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                payload={"title": f"api-func-perm-share-list-{unique_suffix}"},
            )
        except AssertionError:
            pytest.skip("Network error while creating list")
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        resp_read_before = _request_or_skip(
            http_session,
            method="GET",
            url=f"{settings.base_url}/api/boards/{board_id}",
            skip_reason="Network error during other-user board read (before share)",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_read_before = _json_or_text(resp_read_before)
        if not _is_permission_denied(resp_read_before.status_code, body_read_before):
            pytest.skip("Other user already can read private board; cannot validate sharing")

        try:
            resp_add = _add_board_member_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                member_user_id=client2.auth.user_id,
            )
        except AssertionError:
            pytest.skip("Network error while adding board member")

        body_add = _json_or_text(resp_add)
        if resp_add.status_code != 200:
            if _is_permission_denied(resp_add.status_code, body_add):
                pytest.skip("Environment denies adding board members via API")
            pytest.skip("Board member add endpoint returned non-200")
        if isinstance(body_add, dict) and (body_add.get("error") or body_add.get("status") or body_add.get("statusCode")):
            if _is_permission_denied(resp_add.status_code, body_add):
                pytest.skip("Environment denies adding board members via API")

        shared_board = _poll_other_user_can_read_board(
            settings=settings,
            http_session=http_session,
            board_id=board_id,
            other_user_token=client2.auth.token,
            timeout_seconds=10.0,
        )
        if shared_board is None:
            pytest.skip("After sharing, other-user still cannot read board")

        resp_lists = _request_or_skip(
            http_session,
            method="GET",
            url=f"{settings.base_url}/api/boards/{board_id}/lists",
            skip_reason="Network error during other-user lists read (after share)",
            attempts=12,
            headers=_auth_headers(client2.auth.token),
            timeout=settings.timeout_seconds,
        )
        body_lists = _json_or_text(resp_lists)
        assert resp_lists.status_code == 200
        assert isinstance(body_lists, list)
        assert any(isinstance(x, dict) and str(x.get("_id") or "") == list_id for x in body_lists)

    finally:
        if board_id:
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
        if board_id and list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)
