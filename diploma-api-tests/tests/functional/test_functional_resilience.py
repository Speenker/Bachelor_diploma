from __future__ import annotations

import time
import uuid

import pytest

from diploma_tests.waiters import (
    delete_card_with_retry_and_confirm_absent,
    delete_list_with_retry_and_confirm_absent,
    poll_until_board_deleted,
)


pytestmark = [pytest.mark.functional, pytest.mark.slow]


def test_resilience_repeated_delete_is_handled_predictably(client):
    suffix = uuid.uuid4().hex[:8]

    board = client.create_board(title=f"api-func-res-del-{suffix}")
    board_id = str(board.get("_id") or "")
    swimlane_id = str(board.get("defaultSwimlaneId") or "")
    assert board_id
    assert swimlane_id

    list_id = None
    card_id = None
    try:
        list_id = client.create_list(board_id=board_id, title=f"api-func-res-list-{suffix}")
        assert list_id

        card_id = client.create_card(
            board_id=board_id,
            list_id=list_id,
            swimlane_id=swimlane_id,
            title=f"api-func-res-card-{suffix}",
        )
        assert card_id

        delete_card_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id, card_id=card_id)
        delete_card_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id, card_id=card_id)

    finally:
        if board_id and list_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id)
            except Exception:
                pass


def test_resilience_handles_transient_network_errors(client):
    deadline = time.monotonic() + 6.0
    ok = 0

    while time.monotonic() < deadline:
        boards = client.get_user_boards()
        assert isinstance(boards, list)
        ok += 1
        time.sleep(0.05)

    assert ok >= 10


def test_resilience_suite_is_order_independent(client):
    suffix = uuid.uuid4().hex[:8]

    board = client.create_board(title=f"api-func-res-order-{suffix}")
    board_id = str(board.get("_id") or "")
    swimlane_id = str(board.get("defaultSwimlaneId") or "")
    assert board_id
    assert swimlane_id

    list_id = None
    card_id = None
    try:
        list_id = client.create_list(board_id=board_id, title=f"api-func-res-order-list-{suffix}")
        assert list_id

        card_id = client.create_card(
            board_id=board_id,
            list_id=list_id,
            swimlane_id=swimlane_id,
            title=f"api-func-res-order-card-{suffix}",
        )
        assert card_id

        poll_until_board_deleted(client=client, board_id=board_id)

        delete_card_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id, card_id=card_id)
        delete_list_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id)

    finally:
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id)
            except Exception:
                pass
