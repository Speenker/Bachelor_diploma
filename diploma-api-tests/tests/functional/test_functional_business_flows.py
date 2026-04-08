from __future__ import annotations

import time
import uuid

import pytest

from diploma_tests.waiters import (
    delete_card_with_retry_and_confirm_absent,
    delete_list_with_retry_and_confirm_absent,
    poll_until_board_deleted,
    poll_until_card_present_in_list,
)


pytestmark = pytest.mark.functional


def _poll_until_all_cards_present_in_list(
    *,
    client,
    board_id: str,
    list_id: str,
    expected_card_ids: set[str],
    timeout_seconds: float = 6.0,
    attempts: int = 20,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_seen: set[str] = set()
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            cards = client.get_list_cards(board_id=board_id, list_id=list_id)
            last_seen = {str(c.get("_id")) for c in cards if isinstance(c, dict) and c.get("_id")}
            if expected_card_ids.issubset(last_seen):
                return
            last_error = None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.3, max(0.0, remaining / max(1, (attempts - attempt)))))

    missing = sorted(expected_card_ids - last_seen)
    raise AssertionError(f"Not all cards became visible in list. missing_count={len(missing)} last_error={last_error}")


def test_business_flow_create_update_move_delete_card(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_from_id = None
    list_to_id = None
    card_id = None

    board = client.create_board(title=f"api-func-flow-board-{suffix}")
    board_id = str(board.get("_id") or "")
    swimlane_id = str(board.get("defaultSwimlaneId") or "")
    assert board_id
    assert swimlane_id

    try:
        list_from_id = client.create_list(board_id=board_id, title=f"api-func-flow-from-{suffix}")
        list_to_id = client.create_list(board_id=board_id, title=f"api-func-flow-to-{suffix}")
        assert list_from_id
        assert list_to_id

        card_id = client.create_card(
            board_id=board_id,
            list_id=list_from_id,
            swimlane_id=swimlane_id,
            title=f"api-func-flow-card-{suffix}",
            description=f"desc-{suffix}",
        )
        assert card_id

        loaded1 = client.get_card(board_id=board_id, list_id=list_from_id, card_id=card_id)
        assert loaded1 is not None
        assert str(loaded1.get("_id") or "") == card_id

        client.update_card(
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            swimlane_id=swimlane_id,
            title=f"api-func-flow-upd-{suffix}",
            description=f"updated-desc-{suffix}",
            new_list_id=list_from_id,
        )

        client.update_card(
            board_id=board_id,
            list_id=list_from_id,
            card_id=card_id,
            swimlane_id=swimlane_id,
            new_list_id=list_to_id,
        )

        poll_until_card_present_in_list(client=client, board_id=board_id, list_id=list_to_id, card_id=card_id)
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
                poll_until_board_deleted(client=client, board_id=board_id)
            except Exception:
                pass


def test_business_flow_two_boards_entities_do_not_mix(client):
    suffix = uuid.uuid4().hex[:8]

    board1 = client.create_board(title=f"api-func-2b-a-{suffix}")
    board1_id = str(board1.get("_id") or "")
    swimlane1 = str(board1.get("defaultSwimlaneId") or "")
    assert board1_id
    assert swimlane1

    board2 = client.create_board(title=f"api-func-2b-b-{suffix}")
    board2_id = str(board2.get("_id") or "")
    swimlane2 = str(board2.get("defaultSwimlaneId") or "")
    assert board2_id
    assert swimlane2

    list1_id = None
    list2_id = None
    card1_id = None
    card2_id = None

    try:
        list1_id = client.create_list(board_id=board1_id, title=f"api-func-2b-la-{suffix}")
        list2_id = client.create_list(board_id=board2_id, title=f"api-func-2b-lb-{suffix}")
        assert list1_id
        assert list2_id

        card1_id = client.create_card(
            board_id=board1_id,
            list_id=list1_id,
            swimlane_id=swimlane1,
            title=f"api-func-2b-ca-{suffix}",
        )
        card2_id = client.create_card(
            board_id=board2_id,
            list_id=list2_id,
            swimlane_id=swimlane2,
            title=f"api-func-2b-cb-{suffix}",
        )
        assert card1_id
        assert card2_id

        cards_board1_list = client.get_list_cards(board_id=board1_id, list_id=list1_id)
        ids_board1_list = {str(c.get("_id")) for c in cards_board1_list if isinstance(c, dict) and c.get("_id")}
        assert card1_id in ids_board1_list
        assert card2_id not in ids_board1_list

        card2_global = client.get_card_global(card_id=card2_id)
        assert str(card2_global.get("_id") or "") == card2_id
        assert str(card2_global.get("boardId") or "") == board2_id

    finally:
        if board1_id and list1_id and card1_id:
            try:
                delete_card_with_retry_and_confirm_absent(client=client, board_id=board1_id, list_id=list1_id, card_id=card1_id)
            except Exception:
                pass
        if board2_id and list2_id and card2_id:
            try:
                delete_card_with_retry_and_confirm_absent(client=client, board_id=board2_id, list_id=list2_id, card_id=card2_id)
            except Exception:
                pass
        if board1_id and list1_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board1_id, list_id=list1_id)
            except Exception:
                pass
        if board2_id and list2_id:
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board2_id, list_id=list2_id)
            except Exception:
                pass
        try:
            poll_until_board_deleted(client=client, board_id=board1_id)
        except Exception:
            pass
        try:
            poll_until_board_deleted(client=client, board_id=board2_id)
        except Exception:
            pass


def test_business_flow_bulk_create_cards_and_verify_visibility(client):
    suffix = uuid.uuid4().hex[:8]
    count = 10

    board = client.create_board(title=f"api-func-bulk-board-{suffix}")
    board_id = str(board.get("_id") or "")
    swimlane_id = str(board.get("defaultSwimlaneId") or "")
    assert board_id
    assert swimlane_id

    list_id = None
    card_ids: list[str] = []
    try:
        list_id = client.create_list(board_id=board_id, title=f"api-func-bulk-list-{suffix}")
        assert list_id

        for i in range(count):
            card_id = client.create_card(
                board_id=board_id,
                list_id=list_id,
                swimlane_id=swimlane_id,
                title=f"api-func-bulk-{suffix}-{i}",
            )
            card_ids.append(card_id)

        expected = set(card_ids)
        _poll_until_all_cards_present_in_list(client=client, board_id=board_id, list_id=list_id, expected_card_ids=expected)

    finally:
        if board_id and list_id:
            for cid in list(card_ids):
                try:
                    delete_card_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id, card_id=cid)
                except Exception:
                    pass
            try:
                delete_list_with_retry_and_confirm_absent(client=client, board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id)
            except Exception:
                pass
