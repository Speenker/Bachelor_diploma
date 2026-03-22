from __future__ import annotations

import time
import uuid

import pytest

from diploma_tests.client import NetworkError


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


def _poll_until_list_absent(client, *, board_id: str, list_id: str, timeout_seconds: float = 6.0, attempts: int = 12) -> None:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        try:
            lists = client.get_lists(board_id=board_id)
        except NetworkError:
            lists = []

        if not any(str(item.get("_id") or "") == list_id for item in lists):
            return

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))

    raise AssertionError("List still present after deletion")


def test_lists_create_list_returns_id(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_id = None

    board = _create_board_resilient(client, title=f"api-reg-lists-board-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        list_id = client.create_list(board_id=board_id, title=f"api-reg-list-{suffix}")
        assert list_id
    finally:
        if board_id and list_id:
            try:
                client.delete_list(board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_lists_get_lists_contains_created_list(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_id = None
    title = f"api-reg-list-visible-{suffix}"

    board = _create_board_resilient(client, title=f"api-reg-lists-board2-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        list_id = client.create_list(board_id=board_id, title=title)
        assert list_id

        lists = client.get_lists(board_id=board_id)
        assert any(str(item.get("_id") or "") == list_id and item.get("title") == title for item in lists)
    finally:
        if board_id and list_id:
            try:
                client.delete_list(board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_lists_get_list_by_id_returns_expected_fields(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_id = None
    title = f"api-reg-list-get-{suffix}"

    board = _create_board_resilient(client, title=f"api-reg-lists-board3-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        list_id = client.create_list(board_id=board_id, title=title)
        assert list_id

        loaded = client.get_list(board_id=board_id, list_id=list_id)
        assert str(loaded.get("_id") or "") == list_id
        assert loaded.get("title") == title
    finally:
        if board_id and list_id:
            try:
                client.delete_list(board_id=board_id, list_id=list_id)
            except Exception:
                pass
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass


def test_lists_delete_list_removes_from_get_lists(client):
    suffix = uuid.uuid4().hex[:8]
    board_id = None
    list_id = None

    board = _create_board_resilient(client, title=f"api-reg-lists-board4-{suffix}")
    board_id = str(board.get("_id") or "")

    try:
        assert board_id
        list_id = client.create_list(board_id=board_id, title=f"api-reg-list-del-{suffix}")
        assert list_id

        deleted = client.delete_list(board_id=board_id, list_id=list_id)
        assert str(deleted) == str(list_id)

        _poll_until_list_absent(client, board_id=board_id, list_id=list_id)
    finally:
        if board_id:
            try:
                client.delete_board(board_id)
            except Exception:
                pass
