from __future__ import annotations

import time
from typing import Any

from .client import HttpError, NetworkError


def _looks_like_http_404(exc: Exception) -> bool:
    return isinstance(exc, HttpError) and int(exc.status_code) == 404


def _sleep_spread(*, deadline: float, attempt: int, attempts: int, cap_seconds: float) -> None:
    remaining = deadline - time.monotonic()
    if attempt == attempts or remaining <= 0:
        return
    time.sleep(min(cap_seconds, max(0.0, remaining / max(1, (attempts - attempt)))))


def poll_until_list_absent(
    *,
    client: Any,
    board_id: str,
    list_id: str,
    timeout_seconds: float = 2.5,
    attempts: int = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_seen_ids: list[str] = []
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            lists = client.get_lists(board_id=board_id)
            last_seen_ids = [
                str(item.get("_id"))
                for item in lists
                if isinstance(item, dict) and item.get("_id")
            ]
            if str(list_id) not in last_seen_ids:
                return
            last_error = None
        except Exception as exc:
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            if _looks_like_http_404(exc):
                return
            last_error = f"{type(exc).__name__}: {exc}"

        _sleep_spread(deadline=deadline, attempt=attempt, attempts=attempts, cap_seconds=0.25)

    raise AssertionError(
        "List still present after polling. "
        f"list_id={list_id}, board_id={board_id}, seen_ids_count={len(last_seen_ids)}. "
        f"Last error: {last_error}"
    )


def poll_until_card_absent_in_list(
    *,
    client: Any,
    board_id: str,
    list_id: str,
    card_id: str,
    timeout_seconds: float = 2.5,
    attempts: int = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_seen_ids: list[str] = []
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            cards = client.get_list_cards(board_id=board_id, list_id=list_id)
            last_seen_ids = [
                str(item.get("_id"))
                for item in cards
                if isinstance(item, dict) and item.get("_id")
            ]
            if str(card_id) not in last_seen_ids:
                return
            last_error = None
        except Exception as exc:
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            if _looks_like_http_404(exc):
                return
            last_error = f"{type(exc).__name__}: {exc}"

        _sleep_spread(deadline=deadline, attempt=attempt, attempts=attempts, cap_seconds=0.25)

    raise AssertionError(
        "Card still present after delete polling. "
        f"card_id={card_id}, board_id={board_id}, list_id={list_id}, seen_ids_count={len(last_seen_ids)}. "
        f"Last error: {last_error}"
    )


def poll_until_card_present_in_list(
    *,
    client: Any,
    board_id: str,
    list_id: str,
    card_id: str,
    timeout_seconds: float = 2.5,
    attempts: int = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_seen_ids: list[str] = []
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            cards = client.get_list_cards(board_id=board_id, list_id=list_id)
            last_seen_ids = [
                str(item.get("_id"))
                for item in cards
                if isinstance(item, dict) and item.get("_id")
            ]
            if str(card_id) in last_seen_ids:
                return
            last_error = None
        except Exception as exc:
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            last_error = f"{type(exc).__name__}: {exc}"

        _sleep_spread(deadline=deadline, attempt=attempt, attempts=attempts, cap_seconds=0.25)

    raise AssertionError(
        "Card did not appear after polling. "
        f"card_id={card_id}, board_id={board_id}, list_id={list_id}, seen_ids_count={len(last_seen_ids)}. "
        f"Last error: {last_error}"
    )


def delete_list_with_retry_and_confirm_absent(
    *,
    client: Any,
    board_id: str,
    list_id: str,
    timeout_seconds: float = 6.0,
    attempts: int = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            poll_until_list_absent(client=client, board_id=board_id, list_id=list_id, timeout_seconds=0.4, attempts=2)
            return
        except Exception:
            pass

        try:
            client.delete_list(board_id=board_id, list_id=list_id)
            last_error = None
        except Exception as exc:
            if _looks_like_http_404(exc):
                last_error = None
                return
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.35, max(0.0, remaining / max(1, (attempts - attempt)))))

    poll_until_list_absent(client=client, board_id=board_id, list_id=list_id, timeout_seconds=1.5, attempts=8)
    if last_error is not None:
        raise AssertionError(f"List delete not confirmed cleanly. list_id={list_id}, board_id={board_id}. Last error: {last_error}")


def delete_card_with_retry_and_confirm_absent(
    *,
    client: Any,
    board_id: str,
    list_id: str,
    card_id: str,
    timeout_seconds: float = 6.0,
    attempts: int = 10,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            poll_until_card_absent_in_list(
                client=client,
                board_id=board_id,
                list_id=list_id,
                card_id=card_id,
                timeout_seconds=0.4,
                attempts=2,
            )
            return
        except Exception:
            pass

        try:
            client.delete_card(board_id=board_id, list_id=list_id, card_id=card_id)
            last_error = None
        except Exception as exc:
            if _looks_like_http_404(exc):
                last_error = None
                return
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.35, max(0.0, remaining / max(1, (attempts - attempt)))))

    poll_until_card_absent_in_list(
        client=client,
        board_id=board_id,
        list_id=list_id,
        card_id=card_id,
        timeout_seconds=1.5,
        attempts=8,
    )
    if last_error is not None:
        raise AssertionError(
            f"Card delete not confirmed cleanly. card_id={card_id}, board_id={board_id}, list_id={list_id}. Last error: {last_error}"
        )


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
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            cards = client.get_swimlane_cards(board_id=board_id, swimlane_id=swimlane_id)
            last_seen_ids = [
                str(item.get("_id"))
                for item in cards
                if isinstance(item, dict) and item.get("_id")
            ]
            if card_id not in last_seen_ids:
                return
            last_error = None
        except Exception as exc:
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            if _looks_like_http_404(exc):
                return
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - time.monotonic()
        if attempt == attempts or remaining <= 0:
            break
        time.sleep(min(0.2, max(0.0, remaining / max(1, (attempts - attempt)))))

    raise AssertionError(
        "Card still present after delete polling. "
        f"card_id={card_id}, board_id={board_id}, swimlane_id={swimlane_id}, "
        f"seen_ids_count={len(last_seen_ids)}. Last error: {last_error}"
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
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            # Presence check is best-effort. Keep last_error for diagnostics.
            last_error = f"{type(exc).__name__} during board presence check: {exc}"

        try:
            deleted_board_id = client.delete_board(board_id)
            if str(deleted_board_id) == str(board_id):
                return
            last_error = f"Unexpected delete_board response: {deleted_board_id!r}"
        except Exception as exc:
            if not isinstance(exc, (NetworkError, HttpError)):
                raise
            if _looks_like_http_404(exc):
                return
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
