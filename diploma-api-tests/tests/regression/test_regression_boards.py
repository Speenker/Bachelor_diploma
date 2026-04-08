from __future__ import annotations

import time
import uuid

import pytest

from diploma_tests.client import NetworkError
from diploma_tests.waiters import poll_until_board_deleted


pytestmark = pytest.mark.regression


def _recover_board_by_title(client, *, title: str, timeout_seconds: float = 2.0, attempts: int = 5) -> dict[str, str] | None:
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
        time.sleep(min(0.2, max(0.0, remaining / max(1, (attempts - attempt)))))
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
    raise AssertionError("Network error during board creation") from None


def test_boards_create_board_returns_required_fields(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None

    board = _create_board_resilient(client, title=f"api-reg-board-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        assert board.get("defaultSwimlaneId")
    finally:
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=6.0, attempts=8)
            except Exception:
                pass


def test_boards_created_board_visible_in_user_boards(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    title = f"api-reg-board-visible-{suffix}"

    board = _create_board_resilient(client, title=title)
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        boards = client.get_user_boards()
        assert any(b.get("_id") == board_id and b.get("title") == title for b in boards)
    finally:
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=6.0, attempts=8)
            except Exception:
                pass


def test_boards_get_board_returns_same_id(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None

    board = _create_board_resilient(client, title=f"api-reg-board-get-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        loaded = client.get_board(board_id)
        assert str(loaded.get("_id")) == board_id
    finally:
        if board_id:
            try:
                poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=6.0, attempts=8)
            except Exception:
                pass


def test_boards_delete_board_removes_from_user_boards(client):
    suffix = uuid.uuid4().hex[:8]
    title = f"api-reg-board-delete-{suffix}"

    board = _create_board_resilient(client, title=title)
    board_id = str(board.get("_id") or "")
    assert board_id

    deleted_id = client.delete_board(board_id)
    assert str(deleted_id) == board_id

    poll_until_board_deleted(client=client, board_id=board_id, timeout_seconds=8.0, attempts=8)

    boards = client.get_user_boards()
    assert not any(b.get("_id") == board_id for b in boards)
