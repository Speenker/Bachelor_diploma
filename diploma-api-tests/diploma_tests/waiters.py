from __future__ import annotations

import time
from typing import Any


def poll_until_card_absent(
    *,
    client: Any,
    board_id: str,
    swimlane_id: str,
    card_id: str,
    timeout_seconds: float = 2.0,
    attempts: int = 5,
) -> None:
    """Wait until a card is no longer visible in the swimlane cards list.

    This is intentionally small and dependency-free. It is used to reduce flakiness
    caused by eventual consistency or short delays after delete operations.
    """

    deadline = time.monotonic() + timeout_seconds
    last_seen_ids: list[str] = []

    for attempt in range(1, attempts + 1):
        cards = client.get_swimlane_cards(board_id=board_id, swimlane_id=swimlane_id)
        last_seen_ids = [
            str(item.get("_id"))
            for item in cards
            if isinstance(item, dict) and item.get("_id")
        ]
        if card_id not in last_seen_ids:
            return

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.2, max(0.0, remaining / max(1, (attempts - attempt)))))

    raise AssertionError(
        "Card still present after delete polling. "
        f"card_id={card_id}, board_id={board_id}, swimlane_id={swimlane_id}, "
        f"seen_ids_count={len(last_seen_ids)}"
    )


def poll_until_board_deleted(
    *,
    client: Any,
    board_id: str,
    timeout_seconds: float = 8.0,
    attempts: int = 8,
) -> None:
    """Wait until board deletion is confirmed by a successful delete response."""

    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        # If the board is already gone, consider the operation successful.
        try:
            boards = client.get_user_boards()
            existing_ids = {str(b.get("_id")) for b in boards if isinstance(b, dict) and b.get("_id")}
            if str(board_id) not in existing_ids:
                return
        except Exception as exc:
            # Presence check is best-effort. Keep last_error for diagnostics.
            last_error = f"{type(exc).__name__} during board presence check: {exc}"

        try:
            deleted_board_id = client.delete_board(board_id)
            if str(deleted_board_id) == str(board_id):
                return
            last_error = f"Unexpected delete_board response: {deleted_board_id!r}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break

        # Spread waiting across the remaining attempts to better utilize the timeout.
        sleep_seconds = max(0.0, remaining / max(1, (attempts - attempt)))
        time.sleep(min(0.5, sleep_seconds))

    raise AssertionError(
        f"Board deletion not confirmed within timeout. board_id={board_id}. Last error: {last_error}"
    )
