from __future__ import annotations

import time
import uuid

import pytest
import requests

from diploma_tests.client import WekanClient


def _recover_created_board_by_title(
    client: WekanClient,
    *,
    title: str,
    timeout_seconds: float = 2.0,
    attempts: int = 5,
) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout_seconds
    for attempt in range(1, attempts + 1):
        boards = client.get_user_boards()
        match = next((b for b in boards if b.get("title") == title and b.get("_id")), None)
        if match is not None:
            board_id = str(match["_id"])
            return client.get_board(board_id)

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.2, max(0.0, remaining / max(1, (attempts - attempt)))))
    return None


@pytest.fixture(scope="module")
def smoke_board(client: WekanClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    title = f"api-smoke-shared-{suffix}"
    try:
        board = client.create_board(title=title)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        recovered = _recover_created_board_by_title(client, title=title, timeout_seconds=2.0, attempts=5)
        if recovered is None:
            raise
        board = recovered
    board_id = board.get("_id")
    if not board_id:
        raise RuntimeError(f"Smoke board creation returned no _id: {board}")

    try:
        yield board
    finally:
        try:
            client.delete_board(str(board_id))
        except Exception:
            pass


@pytest.fixture(scope="module")
def smoke_board_id(smoke_board: dict[str, str]) -> str:
    return str(smoke_board["_id"])


@pytest.fixture(scope="module")
def smoke_swimlane_id(smoke_board: dict[str, str]) -> str:
    swimlane_id = smoke_board.get("defaultSwimlaneId")
    if not swimlane_id:
        raise RuntimeError(f"Smoke board returned no defaultSwimlaneId: {smoke_board}")
    return str(swimlane_id)


@pytest.fixture()
def smoke_suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def smoke_list(client: WekanClient, smoke_board_id: str, smoke_suffix: str) -> dict[str, str]:
    title = f"todo-{smoke_suffix}"
    list_id = client.create_list(board_id=smoke_board_id, title=title)
    ref: dict[str, str] = {"_id": list_id, "title": title, "deleted": "false"}

    try:
        yield ref
    finally:
        if ref.get("deleted") == "true":
            return
        try:
            client.delete_list(board_id=smoke_board_id, list_id=list_id)
        except Exception:
            pass


@pytest.fixture()
def smoke_second_list(client: WekanClient, smoke_board_id: str, smoke_suffix: str) -> dict[str, str]:
    title = f"done-{smoke_suffix}"
    list_id = client.create_list(board_id=smoke_board_id, title=title)
    ref: dict[str, str] = {"_id": list_id, "title": title, "deleted": "false"}

    try:
        yield ref
    finally:
        if ref.get("deleted") == "true":
            return
        try:
            client.delete_list(board_id=smoke_board_id, list_id=list_id)
        except Exception:
            pass


@pytest.fixture()
def smoke_card(
    client: WekanClient,
    smoke_board_id: str,
    smoke_list: dict[str, str],
    smoke_swimlane_id: str,
    smoke_suffix: str,
) -> dict[str, str]:
    title = f"card-{smoke_suffix}"
    card_id = client.create_card(
        board_id=smoke_board_id,
        list_id=smoke_list["_id"],
        swimlane_id=smoke_swimlane_id,
        title=title,
        description="created by automated smoke test",
    )

    ref: dict[str, str] = {
        "_id": card_id,
        "title": title,
        "list_id": smoke_list["_id"],
        "deleted": "false",
    }

    try:
        yield ref
    finally:
        if ref.get("deleted") == "true":
            return
        try:
            client.delete_card(board_id=smoke_board_id, list_id=ref["list_id"], card_id=card_id)
        except Exception:
            pass
