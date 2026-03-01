from __future__ import annotations

import uuid

import pytest


@pytest.mark.regression
def test_lists_created_list_is_visible_in_get_lists(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_id = None

    board = client.create_board(title=f"api-reg-lists-{suffix}")
    board_id = board["_id"]

    try:
        list_title = f"todo-{suffix}"
        list_id = client.create_list(board_id=board_id, title=list_title)

        lists = client.get_lists(board_id=board_id)
        titles = {item.get("title") for item in lists}

        assert list_title in titles

    finally:
        if list_id and board_id:
            try:
                client.delete_list(board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass
