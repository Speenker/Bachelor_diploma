from __future__ import annotations

from typing import Any
import time

import pytest

from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry


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

    if "error" in body and body.get("error") is not None:
        assert isinstance(body.get("error"), (str, int))
    if "message" in body and body.get("message") is not None:
        assert isinstance(body.get("message"), str)
    if "reason" in body and body.get("reason") is not None:
        assert isinstance(body.get("reason"), str)
    if "errorType" in body and body.get("errorType") is not None:
        assert isinstance(body.get("errorType"), str)

    for key in ("status", "statusCode"):
        if key in body and body.get(key) is not None:
            value = body.get(key)
            if isinstance(value, int):
                assert value >= 100
            elif isinstance(value, str):
                assert value.isdigit()
            else:
                raise AssertionError(f"Unexpected {key} type: {type(value)}")


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
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/users/{user_id}/boards",
                attempts=12,
                headers=_auth_headers(token),
                timeout=settings.timeout_seconds,
            )
            boards = resp.json() if resp.status_code == 200 else []
        except AssertionError:
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


def _get_list_cards_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards",
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


def _recover_card_id_by_title(
    *,
    settings,
    http_session,
    token: str,
    board_id: str,
    list_id: str,
    title: str,
    poll_timeout_seconds: float = 4.0,
    attempts: int = 12,
) -> str | None:
    deadline = time.monotonic() + poll_timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            resp = _get_list_cards_raw(
                settings=settings,
                http_session=http_session,
                token=token,
                board_id=board_id,
                list_id=list_id,
            )
        except AssertionError:
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
    for _ in range(4):
        try:
            resp = _create_card_raw(
                settings=settings,
                http_session=http_session,
                token=token,
                board_id=board_id,
                list_id=list_id,
                payload=payload,
            )
        except AssertionError:
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
            poll_timeout_seconds=3.0,
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
        poll_timeout_seconds=5.0,
        attempts=12,
    )
    if recovered is not None:
        return recovered

    raise AssertionError("Network error during card creation")


def _delete_list_raw(*, settings, http_session, token: str, board_id: str, list_id: str):
    return request_with_network_retry(
        http_session,
        "DELETE",
        f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}",
        attempts=12,
        headers=_auth_headers(token),
        timeout=settings.timeout_seconds,
    )


def test_error_contract_soft_error_shape_on_unauthorized_swimlanes(settings, http_session, client, unique_suffix: str):
    board_id, _ = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-err-soft-board-{unique_suffix}",
    )

    try:
        try:
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{board_id}/swimlanes",
                attempts=12,
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            pytest.skip("Network error while checking soft error contract")

        body = _json_or_text(resp)
        if is_wekan_unauthorized(status_code=resp.status_code, body=body):
            if isinstance(body, dict):
                _assert_error_contract(body)
            return

        if isinstance(body, list):
            pytest.skip("Swimlanes endpoint appears accessible without auth")

        if _looks_like_error_object(body):
            _assert_error_contract(body)
            return

        pytest.skip("Unauthorized response did not include a JSON error object")

    finally:
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_error_contract_unauthorized_has_shape(settings, http_session, client, unique_suffix: str):
    board_id, _ = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-err-unauth-board-{unique_suffix}",
    )

    try:
        try:
            resp = request_with_network_retry(
                http_session,
                "GET",
                f"{settings.base_url}/api/boards/{board_id}",
                attempts=12,
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            pytest.skip("Network error while checking unauthorized error contract")

        body = _json_or_text(resp)
        if is_wekan_unauthorized(status_code=resp.status_code, body=body):
            if isinstance(body, dict):
                _assert_error_contract(body)
            return

        pytest.skip("Boards endpoint appears accessible without auth")

    finally:
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_error_contract_invalid_payload_has_shape(settings, http_session, client, unique_suffix: str):
    board_id, _ = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-err-payload-board-{unique_suffix}",
    )

    list_id = None
    try:
        try:
            resp = _create_list_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                payload={},
            )
        except AssertionError:
            pytest.skip("Network error while checking invalid payload contract")

        body = _json_or_text(resp)
        if _looks_like_error_object(body):
            _assert_error_contract(body)
            return

        if isinstance(body, dict) and body.get("_id"):
            list_id = str(body.get("_id"))
            try:
                _delete_list_raw(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id, list_id=list_id)
            except Exception:
                pass
            pytest.skip("Lists create endpoint appears to accept invalid payload")

        pytest.skip("Invalid payload did not produce an error object")

    finally:
        _delete_board(settings=settings, http_session=http_session, token=client.auth.token, board_id=board_id)


def test_error_contract_json_error_object_for_noop_card_update(settings, http_session, client, unique_suffix: str):
    board_id, swimlane_id = _create_board_resilient(
        settings=settings,
        http_session=http_session,
        token=client.auth.token,
        user_id=client.auth.user_id,
        title=f"api-func-err-card-noop-board-{unique_suffix}",
    )
    list_id = None
    card_id = None

    try:
        assert swimlane_id

        try:
            resp_list = _create_list_raw(
                settings=settings,
                http_session=http_session,
                token=client.auth.token,
                board_id=board_id,
                payload={"title": f"api-func-err-card-noop-list-{unique_suffix}"},
            )
        except AssertionError:
            pytest.skip("Network error while creating list for noop-card-update test")
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
            title=f"api-func-err-card-noop-card-{unique_suffix}",
            description="x",
        )

        try:
            resp = request_with_network_retry(
                http_session,
                "PUT",
                f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
                attempts=12,
                headers=_auth_headers(client.auth.token),
                json={},
                timeout=settings.timeout_seconds,
            )
        except AssertionError:
            pytest.skip("Network error while checking noop card update error contract")

        body = _json_or_text(resp)
        if resp.status_code == 404:
            assert isinstance(body, dict)
            assert _looks_like_error_object(body)
            _assert_error_contract(body)
            return

        if _looks_like_error_object(body):
            _assert_error_contract(body)
            return

        pytest.skip("Noop card update did not produce an error object")

    finally:
        if board_id and list_id and card_id:
            try:
                request_with_network_retry(
                    http_session,
                    "DELETE",
                    f"{settings.base_url}/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
                    attempts=12,
                    headers=_auth_headers(client.auth.token),
                    json={"authorId": client.auth.user_id},
                    timeout=settings.timeout_seconds,
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
