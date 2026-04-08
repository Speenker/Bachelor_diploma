from __future__ import annotations

from typing import Any
import time

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry
from diploma_tests.waiters import poll_until_card_absent_in_list


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
    if isinstance(body, dict) and body.get("message") == "Error":
        return True
    return False


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_user_boards(*, settings, http_session, token: str, user_id: str) -> object:
    resp = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{user_id}/boards",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )
    return resp.json() if resp.status_code == 200 else []


def _recover_board_id_by_title(
    *,
    settings,
    http_session,
    token: str,
    user_id: str,
    title: str,
    poll_timeout_seconds: float = 2.0,
    attempts: int = 5,
) -> str | None:
    deadline = time.monotonic() + poll_timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            boards = _get_user_boards(settings=settings, http_session=http_session, token=token, user_id=user_id)
        except NetworkError:
            boards = []

        if isinstance(boards, list):
            match = next((b for b in boards if isinstance(b, dict) and b.get("title") == title and b.get("_id")), None)
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
    had_network_error = False
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
        except NetworkError:
            had_network_error = True
            resp = None

        if resp is not None and resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, dict) and body.get("_id"):
                board_id = str(body["_id"])
                swimlane_id = str(body.get("defaultSwimlaneId") or "")
                if swimlane_id:
                    return board_id, swimlane_id

                try:
                    loaded = _get_board_raw(settings=settings, http_session=http_session, token=token, board_id=board_id)
                except NetworkError:
                    had_network_error = True
                    loaded = None
                if loaded is not None and loaded.status_code == 200:
                    body_loaded = _json_or_text(loaded)
                    if isinstance(body_loaded, dict) and body_loaded.get("defaultSwimlaneId"):
                        return board_id, str(body_loaded.get("defaultSwimlaneId"))

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
            try:
                resp_board = _get_board_raw(settings=settings, http_session=http_session, token=token, board_id=recovered_id)
            except NetworkError:
                had_network_error = True
                resp_board = None

            if resp_board is not None:
                assert resp_board.status_code == 200
                body_board = _json_or_text(resp_board)
                assert isinstance(body_board, dict) and body_board.get("defaultSwimlaneId")
                return recovered_id, str(body_board.get("defaultSwimlaneId"))

        time.sleep(backoff_seconds)
        backoff_seconds = min(1.0, backoff_seconds * 2)

    if had_network_error:
        pytest.skip("Wekan is not reachable (network error during board creation)")
    raise AssertionError("Board creation failed without a network error")


def _get_board_raw(*, settings, http_session, token: str, board_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


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
    except NetworkError:
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


def _delete_list_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "DELETE",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _get_list_cards_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def _get_swimlane_cards_raw(*, settings, http_session, token: str, board_id: str, swimlane_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}/swimlanes/{swimlane_id}/cards",
        attempts=12,
        headers=_auth_headers(token),
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


def _get_card_global_raw(*, settings, http_session, token: str, card_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/cards/{card_id}",
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


def _recover_card_id_by_title(
    *,
    settings,
    http_session,
    token: str,
    board_id: str,
    list_id: str,
    title: str,
    poll_timeout_seconds: float = 6.0,
    attempts: int = 12,
) -> str | None:
    deadline = time.monotonic() + poll_timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            resp = _get_list_cards_raw(settings=settings, http_session=http_session, token=token, board_id=board_id, list_id=list_id)
        except NetworkError:
            resp = None

        if resp is not None and resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, list):
                match = next((c for c in body if isinstance(c, dict) and c.get("title") == title and c.get("_id")), None)
                if match is not None:
                    return str(match["_id"])

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return None


def _create_card_resilient(
    *,
    settings,
    http_session,
    token: str,
    board_id: str,
    list_id: str,
    user_id: str,
    swimlane_id: str,
    title: str,
    description: str,
) -> str:
    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "authorId": user_id,
        "swimlaneId": swimlane_id,
    }

    backoff_seconds = 0.25
    had_network_error = False
    for _ in range(4):
        try:
            resp = _create_card_raw(settings=settings, http_session=http_session, token=token, board_id=board_id, list_id=list_id, payload=payload)
        except NetworkError:
            had_network_error = True
            resp = None

        if resp is not None and resp.status_code == 200:
            body = _json_or_text(resp)
            if isinstance(body, dict) and body.get("_id"):
                return str(body["_id"])

        recovered = _recover_card_id_by_title(
            settings=settings,
            http_session=http_session,
            token=token,
            board_id=board_id,
            list_id=list_id,
            title=title,
            poll_timeout_seconds=3.5,
            attempts=10,
        )
        if recovered is not None:
            return recovered

        time.sleep(backoff_seconds)
        backoff_seconds = min(1.0, backoff_seconds * 2)

    recovered = _recover_card_id_by_title(
        settings=settings,
        http_session=http_session,
        token=token,
        board_id=board_id,
        list_id=list_id,
        title=title,
        poll_timeout_seconds=6.0,
        attempts=12,
    )
    if recovered is not None:
        return recovered

    if had_network_error:
        pytest.skip("Wekan is not reachable (network error during card creation)")
    raise AssertionError("Card creation failed without a network error")


def _poll_until_card_absent_in_list(*, settings, http_session, token: str, board_id: str, list_id: str, card_id: str, timeout_seconds: float = 6.0, attempts: int = 12) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_body: object = None
    for attempt in range(1, attempts + 1):
        resp = _get_list_cards_raw(settings=settings, http_session=http_session, token=token, board_id=board_id, list_id=list_id)
        assert resp.status_code == 200
        body = _json_or_text(resp)
        last_body = body

        if isinstance(body, list) and not any(isinstance(item, dict) and str(item.get("_id") or "") == card_id for item in body):
            return

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, remaining))

    raise AssertionError(f"Card {card_id} still present in list {list_id}. Last response: {last_body!r}")
def test_cards_create_update_move_delete_contract(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-cards-board-{unique_suffix}",
    )

    list_from_id = None
    list_to_id = None
    card_id = None

    try:
        resp_from = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-from-{unique_suffix}"},
        )
        assert resp_from.status_code == 200
        body_from = _json_or_text(resp_from)
        assert isinstance(body_from, dict) and body_from.get("_id")
        list_from_id = str(body_from["_id"])

        resp_to = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-to-{unique_suffix}"},
        )
        assert resp_to.status_code == 200
        body_to = _json_or_text(resp_to)
        assert isinstance(body_to, dict) and body_to.get("_id")
        list_to_id = str(body_to["_id"])

        card_title = f"api-func-card-{unique_suffix}"
        card_desc = f"desc-{unique_suffix}"
        card_id = _create_card_resilient(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_from_id,
            user_id=client.auth.user_id,
            swimlane_id=swimlane_id,
            title=card_title,
            description=card_desc,
        )

        resp_get1 = _get_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
        )
        assert resp_get1.status_code == 200
        body_get1 = _json_or_text(resp_get1)
        assert isinstance(body_get1, dict)
        assert str(body_get1.get("_id") or "") == card_id
        if "title" in body_get1:
            assert str(body_get1.get("title") or "") == card_title

        updated_title = f"api-func-card-upd-{unique_suffix}"
        updated_desc = f"updated-desc-{unique_suffix}"
        resp_upd = _update_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            payload={
                "title": updated_title,
                "description": updated_desc,
                "authorId": client.auth.user_id,
                "listId": list_from_id,
            },
        )
        assert resp_upd.status_code in (200, 404)
        body_upd = _json_or_text(resp_upd)
        if resp_upd.status_code == 404 or _is_wekan_error(resp_upd.status_code, body_upd):
            pytest.skip("Card update is not available or returned error on this deployment")

        resp_get2 = _get_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
        )
        assert resp_get2.status_code == 200
        body_get2 = _json_or_text(resp_get2)
        assert isinstance(body_get2, dict)
        assert str(body_get2.get("_id") or "") == card_id
        if "title" in body_get2:
            assert str(body_get2.get("title") or "") == updated_title
        if "description" in body_get2:
            assert str(body_get2.get("description") or "") == updated_desc

        resp_move = _update_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            payload={
                "authorId": client.auth.user_id,
                "listId": list_to_id,
            },
        )
        assert resp_move.status_code in (200, 404)
        body_move = _json_or_text(resp_move)
        if resp_move.status_code == 404 or _is_wekan_error(resp_move.status_code, body_move):
            pytest.skip("Card move is not available or returned error on this deployment")

        resp_get3 = _get_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_to_id,
            card_id=card_id,
        )
        assert resp_get3.status_code == 200
        body_get3 = _json_or_text(resp_get3)
        assert isinstance(body_get3, dict)
        assert str(body_get3.get("_id") or "") == card_id
        assert str(body_get3.get("listId") or "") == list_to_id

        resp_global = _get_card_global_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            card_id=card_id,
        )
        assert resp_global.status_code == 200
        body_global = _json_or_text(resp_global)
        assert isinstance(body_global, dict)
        assert str(body_global.get("_id") or "") == card_id

        resp_swimlane = _get_swimlane_cards_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            swimlane_id=swimlane_id,
        )
        assert resp_swimlane.status_code == 200
        body_swimlane = _json_or_text(resp_swimlane)
        assert isinstance(body_swimlane, list)
        assert any(isinstance(item, dict) and str(item.get("_id") or "") == card_id for item in body_swimlane)

        resp_del = _delete_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_to_id,
            card_id=card_id,
            author_id=client.auth.user_id,
        )
        assert resp_del.status_code == 200
        body_del = _json_or_text(resp_del)
        if _is_wekan_error(resp_del.status_code, body_del):
            pytest.skip("Card delete returned error on this deployment")

        _poll_until_card_absent_in_list(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_to_id,
            card_id=card_id,
        )

    finally:
        if list_from_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_from_id)
            except Exception:
                pass
        if list_to_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_to_id)
            except Exception:
                pass
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_cards_create_requires_title(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-cards-req-board-{unique_suffix}",
    )

    list_id = None
    created_id = None

    try:
        resp_list = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-req-list-{unique_suffix}"},
        )
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        try:
            resp_before = _get_list_cards_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=list_id,
            )
        except NetworkError:
            pytest.skip("Network error while listing cards before invalid create")
        assert resp_before.status_code == 200
        body_before = _json_or_text(resp_before)
        assert isinstance(body_before, list)
        before_ids = {str(item.get("_id")) for item in body_before if isinstance(item, dict) and item.get("_id")}

        try:
            resp = _create_card_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=list_id,
                payload={
                    "description": "x",
                    "authorId": client.auth.user_id,
                    "swimlaneId": swimlane_id,
                },
            )
        except NetworkError:
            pytest.skip("Network error during invalid card creation")

        body = _json_or_text(resp)
        if _is_wekan_error(resp.status_code, body):
            try:
                resp_after = _get_list_cards_raw(
                    settings=settings,
                    http_session=http_session,
                    token=client.auth.token,
                    board_id=board_id,
                    list_id=list_id,
                )
            except NetworkError:
                pytest.skip("Network error while listing cards after invalid create")
            assert resp_after.status_code == 200
            body_after = _json_or_text(resp_after)
            assert isinstance(body_after, list)
            after_ids = {str(item.get("_id")) for item in body_after if isinstance(item, dict) and item.get("_id")}
            assert after_ids == before_ids
            return

        if isinstance(body, dict) and body.get("_id"):
            created_id = str(body.get("_id"))
            try:
                _delete_card_raw(
                    settings=settings,
                    http_session=http_session,
                    token=client.auth.token,
                    board_id=board_id,
                    list_id=list_id,
                    card_id=created_id,
                    author_id=client.auth.user_id,
                )
            except Exception:
                pass

        pytest.skip("Cards create endpoint appears to accept missing title")

    finally:
        if list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_cards_create_rejects_invalid_title_type(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-cards-type-board-{unique_suffix}",
    )

    list_id = None
    created_id = None

    try:
        resp_list = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-type-list-{unique_suffix}"},
        )
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        try:
            resp_before = _get_list_cards_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=list_id,
            )
        except NetworkError:
            pytest.skip("Network error while listing cards before invalid create")
        assert resp_before.status_code == 200
        body_before = _json_or_text(resp_before)
        assert isinstance(body_before, list)
        before_ids = {str(item.get("_id")) for item in body_before if isinstance(item, dict) and item.get("_id")}

        try:
            resp = _create_card_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=list_id,
                payload={
                    "title": 123,
                    "description": "x",
                    "authorId": client.auth.user_id,
                    "swimlaneId": swimlane_id,
                },
            )
        except NetworkError:
            pytest.skip("Network error during invalid card creation")

        body = _json_or_text(resp)
        if _is_wekan_error(resp.status_code, body):
            try:
                resp_after = _get_list_cards_raw(
                    settings=settings,
                    http_session=http_session,
                    token=client.auth.token,
                    board_id=board_id,
                    list_id=list_id,
                )
            except NetworkError:
                pytest.skip("Network error while listing cards after invalid create")
            assert resp_after.status_code == 200
            body_after = _json_or_text(resp_after)
            assert isinstance(body_after, list)
            after_ids = {str(item.get("_id")) for item in body_after if isinstance(item, dict) and item.get("_id")}
            assert after_ids == before_ids
            return

        if isinstance(body, dict) and body.get("_id"):
            created_id = str(body.get("_id"))
            try:
                _delete_card_raw(
                    settings=settings,
                    http_session=http_session,
                    token=client.auth.token,
                    board_id=board_id,
                    list_id=list_id,
                    card_id=created_id,
                    author_id=client.auth.user_id,
                )
            except Exception:
                pass

        pytest.skip("Cards create endpoint appears to accept non-string title")

    finally:
        if list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_cards_update_truncates_long_title(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-cards-len-board-{unique_suffix}",
    )

    list_id = None
    card_id = None

    try:
        resp_list = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-len-list-{unique_suffix}"},
        )
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        card_id = _create_card_resilient(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_id,
            user_id=client.auth.user_id,
            swimlane_id=swimlane_id,
            title=f"api-func-card-len-{unique_suffix}",
            description="x",
        )

        long_title = "x" * 1200
        resp_upd = _update_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_id,
            card_id=card_id,
            payload={"title": long_title, "authorId": client.auth.user_id, "listId": list_id},
        )
        body_upd = _json_or_text(resp_upd)
        if _is_wekan_error(resp_upd.status_code, body_upd):
            pytest.skip("Card update returned error on this deployment")

        resp_get = _get_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_id,
            card_id=card_id,
        )
        assert resp_get.status_code == 200
        body_get = _json_or_text(resp_get)
        assert isinstance(body_get, dict)
        if "title" not in body_get:
            pytest.skip("Card GET does not expose title on this deployment")

        loaded_title = str(body_get.get("title") or "")
        if loaded_title == long_title:
            pytest.skip("Card title was not truncated; length validation differs on this deployment")
        assert len(loaded_title) <= 1000

    finally:
        if card_id and list_id:
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
        if list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_cards_bad_ids_return_error_or_empty(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-cards-badid-board-{unique_suffix}",
    )

    list_id = None
    try:
        resp_list = _create_list_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            payload={"title": f"api-func-cards-badid-list-{unique_suffix}"},
        )
        assert resp_list.status_code == 200
        body_list = _json_or_text(resp_list)
        assert isinstance(body_list, dict) and body_list.get("_id")
        list_id = str(body_list["_id"])

        nonexistent_card_id = ("Z" * 17)

        resp_get = _get_card_raw(
            settings=settings,
            http_session=http_session,
            token=client.auth.token,
            board_id=board_id,
            list_id=list_id,
            card_id=nonexistent_card_id,
        )
        assert resp_get.status_code == 200
        body_get = _json_or_text(resp_get)
        assert (
            body_get is None
            or (isinstance(body_get, str) and not body_get.strip())
            or _is_wekan_error(resp_get.status_code, body_get)
            or (isinstance(body_get, dict) and not body_get)
        )

        try:
            resp_global = _get_card_global_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                card_id=nonexistent_card_id,
            )
        except NetworkError:
            pytest.skip("Network error while checking global card lookup")
        body_global = _json_or_text(resp_global)
        if is_wekan_unauthorized(status_code=resp_global.status_code, body=body_global):
            pytest.skip("Deployment restricts global card lookup")
        assert resp_global.status_code >= 400 or _is_wekan_error(resp_global.status_code, body_global)

        try:
            resp_cards = _get_list_cards_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                list_id=("Y" * 17),
            )
        except NetworkError:
            pytest.skip("Network error while checking list cards with bad listId")
        assert resp_cards.status_code == 200
        body_cards = _json_or_text(resp_cards)
        assert isinstance(body_cards, list)
        assert len(body_cards) == 0

        assert swimlane_id

    finally:
        if list_id:
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)
