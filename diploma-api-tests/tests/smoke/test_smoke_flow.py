from __future__ import annotations

import time

import pytest

from diploma_tests.config import Settings
from diploma_tests.http_helpers import is_wekan_unauthorized, request_with_network_retry
from diploma_tests.waiters import (
    delete_card_with_retry_and_confirm_absent,
    delete_list_with_retry_and_confirm_absent,
    poll_until_board_deleted,
    poll_until_card_absent,
)


pytestmark = [pytest.mark.smoke, pytest.mark.regression]


 


def test_smoke_login_success_token_works(settings: Settings, http_session):
    payload: dict[str, str] = {"password": settings.password or ""}
    if settings.username:
        payload["username"] = settings.username
    elif settings.email:
        payload["email"] = settings.email
    else:
        pytest.skip("No WEKAN_USERNAME/WEKAN_EMAIL configured")

    resp = request_with_network_retry(
        http_session,
        "POST",
        f"{settings.base_url}/users/login",
        attempts=8,
        json=payload,
        timeout=settings.timeout_seconds,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, dict)
    assert data.get("token")
    assert data.get("id")

    token = str(data["token"])
    user_id = str(data["id"])

    resp2 = request_with_network_retry(
        http_session,
        "GET",
        f"{settings.base_url}/api/users/{user_id}/boards",
        attempts=5,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.timeout_seconds,
    )
    assert resp2.status_code == 200, resp2.text
    assert isinstance(resp2.json(), list)


def test_smoke_access_denied_without_authorization(settings: Settings, http_session, client):
    url = f"{settings.base_url}/api/users/{client.auth.user_id}/boards"
    last_exc: Exception | None = None
    resp = None
    for attempt in range(3):
        try:
            resp = http_session.get(url, timeout=settings.timeout_seconds)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.1 * (2**attempt))

    if resp is None:
        raise AssertionError(f"GET without auth failed due to network error: {last_exc}")

    if resp.status_code in (401, 403):
        return

    assert resp.status_code == 200, resp.text
    assert is_wekan_unauthorized(status_code=resp.status_code, body=resp.json()), resp.text


def test_smoke_create_board_returns_ids(smoke_board: dict[str, str]):
    assert smoke_board.get("_id")
    assert smoke_board.get("defaultSwimlaneId")


def test_smoke_get_swimlanes_non_empty(client, smoke_board_id: str, smoke_swimlane_id: str):
    swimlanes = client.get_swimlanes(board_id=smoke_board_id)
    assert swimlanes
    assert any(item.get("_id") == smoke_swimlane_id for item in swimlanes)


def test_smoke_create_list_returns_id(smoke_list: dict[str, str]):
    assert smoke_list.get("_id")


def test_smoke_get_lists_contains_created(client, smoke_board_id: str, smoke_list: dict[str, str]):
    lists = client.get_lists(board_id=smoke_board_id)
    assert any(item.get("_id") == smoke_list["_id"] for item in lists)
    assert any(item.get("title") == smoke_list["title"] for item in lists)


def test_smoke_create_card_returns_id(smoke_card: dict[str, str]):
    assert smoke_card.get("_id")


def test_smoke_get_cards_by_swimlane_contains_created(client, smoke_board_id: str, smoke_swimlane_id: str, smoke_card: dict[str, str]):
    cards = client.get_swimlane_cards(board_id=smoke_board_id, swimlane_id=smoke_swimlane_id)
    assert any(item.get("_id") == smoke_card["_id"] for item in cards)


def test_smoke_update_card_title_persists(client, smoke_board_id: str, smoke_swimlane_id: str, smoke_card: dict[str, str]):
    new_title = f"{smoke_card['title']}-updated"
    client.update_card(
        board_id=smoke_board_id,
        list_id=smoke_card["list_id"],
        card_id=smoke_card["_id"],
        swimlane_id=smoke_swimlane_id,
        title=new_title,
    )

    cards = client.get_swimlane_cards(board_id=smoke_board_id, swimlane_id=smoke_swimlane_id)
    updated = next((c for c in cards if c.get("_id") == smoke_card["_id"]), None)
    assert updated is not None
    assert updated.get("title") == new_title


def test_smoke_move_card_to_another_list(
    client,
    smoke_board_id: str,
    smoke_swimlane_id: str,
    smoke_second_list: dict[str, str],
    smoke_card: dict[str, str],
):
    client.update_card(
        board_id=smoke_board_id,
        list_id=smoke_card["list_id"],
        card_id=smoke_card["_id"],
        swimlane_id=smoke_swimlane_id,
        new_list_id=smoke_second_list["_id"],
    )

    smoke_card["list_id"] = smoke_second_list["_id"]

    cards = client.get_swimlane_cards(board_id=smoke_board_id, swimlane_id=smoke_swimlane_id)
    moved = next((c for c in cards if c.get("_id") == smoke_card["_id"]), None)
    assert moved is not None

    assert moved.get("listId") == smoke_second_list["_id"]


def test_smoke_delete_card_confirmed_with_polling(
    client,
    smoke_board_id: str,
    smoke_swimlane_id: str,
    smoke_list: dict[str, str],
    smoke_suffix: str,
):
    card_id = client.create_card(
        board_id=smoke_board_id,
        list_id=smoke_list["_id"],
        swimlane_id=smoke_swimlane_id,
        title=f"delete-{smoke_suffix}",
    )

    delete_card_with_retry_and_confirm_absent(client=client, board_id=smoke_board_id, list_id=smoke_list["_id"], card_id=card_id, timeout_seconds=4.0, attempts=10)

    poll_until_card_absent(
        client=client,
        board_id=smoke_board_id,
        swimlane_id=smoke_swimlane_id,
        card_id=card_id,
        timeout_seconds=2.0,
        attempts=5,
    )


def test_smoke_cleanup_delete_list_and_board_best_effort(client, smoke_suffix: str):
    board = client.create_board(title=f"api-smoke-cleanup-{smoke_suffix}")
    board_id = board.get("_id")
    assert board_id

    list_id = None
    try:
        list_id = client.create_list(board_id=str(board_id), title=f"cleanup-{smoke_suffix}")
        assert list_id

        deleted_list_id = client.delete_list(board_id=str(board_id), list_id=str(list_id))
        assert deleted_list_id == str(list_id)

        poll_until_board_deleted(client=client, board_id=str(board_id), timeout_seconds=8.0, attempts=8)
    finally:
        if list_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=str(board_id), list_id=str(list_id), timeout_seconds=4.0, attempts=10)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(str(board_id))
            except Exception:
                pass
