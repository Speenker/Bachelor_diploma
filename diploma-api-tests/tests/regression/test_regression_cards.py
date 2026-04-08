from __future__ import annotations

import time
import uuid

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.waiters import (
    delete_card_with_retry_and_confirm_absent,
    delete_list_with_retry_and_confirm_absent,
    poll_until_card_present_in_list,
)


pytestmark = pytest.mark.regression


def _recover_board_by_title(client, *, title: str, timeout_seconds: float = 8.0, attempts: int = 20) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            boards = client.get_user_boards()
        except NetworkError:
            boards = []

        match = next((b for b in boards if b.get("title") == title and b.get("_id")), None)
        if match is not None:
            board_id = str(match["_id"])
            try:
                return client.get_board(board_id)
            except NetworkError:
                pass

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return None


def _create_board_resilient(client, *, title: str) -> dict[str, str]:
    backoff_seconds = 0.25
    for _ in range(5):
        try:
            return client.create_board(title=title)
        except NetworkError:
            recovered = _recover_board_by_title(client, title=title, timeout_seconds=4.0, attempts=12)
            if recovered is not None:
                return recovered
            time.sleep(backoff_seconds)
            backoff_seconds = min(1.0, backoff_seconds * 2)

    recovered = _recover_board_by_title(client, title=title, timeout_seconds=8.0, attempts=20)
    if recovered is not None:
        return recovered
    raise AssertionError("Network error during board creation")


def _recover_card_id_by_title(
    client,
    *,
    board_id: str,
    list_id: str,
    title: str,
    timeout_seconds: float = 6.0,
    attempts: int = 12,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            cards = client.get_list_cards(board_id=board_id, list_id=list_id)
        except NetworkError:
            cards = []

        match = next((c for c in cards if c.get("title") == title and c.get("_id")), None)
        if match is not None:
            return str(match["_id"])

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    return None


def _create_card_resilient(client, *, board_id: str, list_id: str, swimlane_id: str, title: str, description: str) -> str:
    backoff_seconds = 0.25
    for _ in range(4):
        try:
            return client.create_card(
                board_id=board_id,
                list_id=list_id,
                swimlane_id=swimlane_id,
                title=title,
                description=description,
            )
        except NetworkError:
            recovered = _recover_card_id_by_title(
                client,
                board_id=board_id,
                list_id=list_id,
                title=title,
                timeout_seconds=3.5,
                attempts=10,
            )
            if recovered is not None:
                return recovered
            time.sleep(backoff_seconds)
            backoff_seconds = min(1.0, backoff_seconds * 2)

    recovered = _recover_card_id_by_title(client, board_id=board_id, list_id=list_id, title=title, timeout_seconds=6.0, attempts=12)
    if recovered is not None:
        return recovered
    raise AssertionError("Network error during card creation")


def test_cards_business_flow_create_update_move_delete_with_reads(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_from_id = None
    list_to_id = None
    card_id = None

    board = _create_board_resilient(client, title=f"api-reg-cards-board-{suffix}")
    board_id = str(board.get("_id") or "")
    swimlane_id = str(board.get("defaultSwimlaneId") or "")

    try:
        assert board_id
        assert swimlane_id

        list_from_id = client.create_list(board_id=board_id, title=f"api-reg-cards-from-{suffix}")
        list_to_id = client.create_list(board_id=board_id, title=f"api-reg-cards-to-{suffix}")
        assert list_from_id
        assert list_to_id

        title = f"api-reg-card-{suffix}"
        description = f"desc-{suffix}"
        card_id = _create_card_resilient(
            client,
            board_id=board_id,
            list_id=list_from_id,
            swimlane_id=swimlane_id,
            title=title,
            description=description,
        )
        assert card_id

        loaded1 = client.get_card(board_id=board_id, list_id=list_from_id, card_id=card_id)
        assert loaded1 is not None
        assert str(loaded1.get("_id") or "") == card_id
        assert str(loaded1.get("boardId") or "") == board_id
        assert str(loaded1.get("listId") or "") == list_from_id
        assert str(loaded1.get("swimlaneId") or "") == swimlane_id
        if "title" in loaded1:
            assert str(loaded1.get("title") or "") == title

        updated_title = f"api-reg-card-upd-{suffix}"
        updated_desc = f"updated-desc-{suffix}"
        client.update_card(
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            swimlane_id=swimlane_id,
            title=updated_title,
            description=updated_desc,
            new_list_id=list_from_id,
        )

        loaded2 = client.get_card(board_id=board_id, list_id=list_from_id, card_id=card_id)
        assert loaded2 is not None
        assert str(loaded2.get("_id") or "") == card_id
        if "title" in loaded2:
            assert str(loaded2.get("title") or "") == updated_title
        if "description" in loaded2:
            assert str(loaded2.get("description") or "") == updated_desc

        client.update_card(
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            swimlane_id=swimlane_id,
            new_list_id=list_to_id,
        )

        poll_until_card_present_in_list(client=client, board_id=board_id, list_id=list_to_id, card_id=card_id)

        loaded3 = client.get_card(board_id=board_id, list_id=list_to_id, card_id=card_id)
        assert loaded3 is not None
        assert str(loaded3.get("_id") or "") == card_id
        assert str(loaded3.get("listId") or "") == list_to_id

        delete_card_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_to_id, card_id=card_id)

    finally:
        if board_id and list_from_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_from_id)
            except Exception:
                pass
        if board_id and list_to_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_to_id)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass
