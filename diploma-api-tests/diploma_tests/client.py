from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from urllib3.util.retry import Retry

from .config import Settings


@dataclass
class Auth:
    user_id: str
    token: str


class NetworkError(RuntimeError):
    pass


class HttpError(RuntimeError):
    def __init__(self, *, method: str, path: str, status_code: int, body: Any) -> None:
        super().__init__(f"{method} {path} failed: {status_code} {body}")
        self.method = method
        self.path = path
        self.status_code = status_code
        self.body = body


def _is_network_exception(exc: BaseException) -> bool:
    # requests wraps many underlying socket/urllib3 errors into RequestException,
    # but not always reliably across platforms/backends.
    if isinstance(exc, (requests.exceptions.RequestException, OSError, Urllib3HTTPError)):
        return True
    return False


class WekanClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        retry = Retry(
            total=3,
            # Do not retry connection/read errors globally (especially for POST).
            connect=False,
            read=False,
            status=3,
            backoff_factor=0.25,
            status_forcelist=(502, 503, 504),
            # Do not retry POST globally.
            allowed_methods=("GET", "PUT", "DELETE"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._auth: Auth | None = None

    @property
    def auth(self) -> Auth:
        if self._auth is None:
            raise RuntimeError("Client is not authenticated. Call login().")
        return self._auth

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth is not None:
            headers["Authorization"] = f"Bearer {self._auth.token}"
        return headers

    def _request(self, method: str, path: str, *, json: Any | None = None) -> Any:
        # Keep network retries limited to safe methods.
        safe_methods = {"GET", "PUT", "DELETE"}
        method_upper = method.upper()
        attempts = 6 if method_upper in safe_methods else 1

        last_exc: Exception | None = None
        resp: requests.Response | None = None
        for attempt in range(attempts):
            try:
                resp = self.session.request(
                    method_upper,
                    self._url(path),
                    headers=self._headers(),
                    json=json,
                    timeout=self.timeout_seconds,
                )
                last_exc = None
                break
            except Exception as exc:
                if not _is_network_exception(exc):
                    raise
                last_exc = exc
                if attempt + 1 < attempts:
                    time.sleep(0.25 * (2**attempt))

        if resp is None:
            message = f"{method_upper} {path} network error: {type(last_exc).__name__ if last_exc else 'UnknownError'}"
            raise NetworkError(message) from None

        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = resp.text

        if resp.status_code >= 400:
            raise HttpError(method=method_upper, path=path, status_code=int(resp.status_code), body=data)
        return data

    @classmethod
    def from_settings(cls, settings: Settings) -> "WekanClient":
        client = cls(settings.base_url, timeout_seconds=settings.timeout_seconds)
        if not settings.has_login_credentials:
            raise RuntimeError(
                "Missing Wekan credentials. Set WEKAN_USERNAME (or WEKAN_EMAIL) and WEKAN_PASSWORD in .env. "
                "(Auto-registration via /users/register may be disabled and can return 403.)"
            )

        client.login(username=settings.username, email=settings.email, password=settings.password or "")
        return client

    def login(self, *, username: str | None, email: str | None, password: str) -> Auth:
        payload: dict[str, str] = {"password": password}
        if username:
            payload["username"] = username
        elif email:
            payload["email"] = email
        else:
            raise ValueError("username or email must be provided")

        # Targeted network retry for login only (safe and idempotent).
        last_exc: Exception | None = None
        data: Any | None = None
        for attempt in range(5):
            try:
                data = self._request("POST", "/users/login", json=payload)
                last_exc = None
                break
            except NetworkError as exc:
                last_exc = exc
                if attempt < 4:
                    # 0.1s, 0.2s, 0.4s, 0.8s
                    time.sleep(0.1 * (2**attempt))

        if data is None:
            raise NetworkError(f"POST /users/login failed after retries: {last_exc}")
        if not isinstance(data, dict) or "token" not in data or "id" not in data:
            raise RuntimeError(f"Unexpected login response: {data}")

        self._auth = Auth(user_id=str(data["id"]), token=str(data["token"]))
        return self._auth

    def register(self, *, username: str, email: str, password: str) -> Auth:
        data = self._request(
            "POST",
            "/users/register",
            json={"username": username, "email": email, "password": password},
        )
        if not isinstance(data, dict) or "token" not in data or "id" not in data:
            raise RuntimeError(f"Unexpected register response: {data}")

        self._auth = Auth(user_id=str(data["id"]), token=str(data["token"]))
        return self._auth

    def create_board(self, *, title: str, permission: str = "private", color: str = "nephritis") -> dict[str, str]:
        payload = {
            "title": title,
            "owner": self.auth.user_id,
            "permission": permission,
            "color": color,
        }
        backoff_seconds = 0.15
        for attempt in range(1, 4):
            try:
                data = self._request("POST", "/api/boards", json=payload)
                if not isinstance(data, dict) or "_id" not in data:
                    raise RuntimeError(f"Unexpected create_board response: {data}")
                return {k: str(v) for k, v in data.items()}
            except NetworkError:
                recovered = self._recover_board_by_title(title=title, timeout_seconds=3.0, attempts=12)
                if recovered is not None:
                    return recovered
                if attempt < 3:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(0.6, backoff_seconds * 2)

        recovered = self._recover_board_by_title(title=title, timeout_seconds=6.0, attempts=20)
        if recovered is not None:
            return recovered
        raise NetworkError("Network error during board creation")


    def _recover_board_by_title(self, *, title: str, timeout_seconds: float, attempts: int) -> dict[str, str] | None:
        deadline = time.monotonic() + timeout_seconds
        for attempt in range(1, attempts + 1):
            try:
                boards = self.get_user_boards()
            except (NetworkError, HttpError):
                boards = []

            match = next((b for b in boards if b.get("title") == title and b.get("_id")), None)
            if match is not None:
                board_id = str(match.get("_id") or "")
                if board_id:
                    try:
                        return self.get_board(board_id)
                    except (NetworkError, HttpError):
                        return {k: str(v) for k, v in match.items()}

            remaining = deadline - time.monotonic()
            if attempt == attempts or remaining <= 0:
                break
            time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))
        return None

    def get_board(self, board_id: str) -> dict[str, str]:
        data = self._request("GET", f"/api/boards/{board_id}")
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected get_board response: {data}")
        return {k: str(v) for k, v in data.items()}

    def delete_board(self, board_id: str) -> str:
        data = self._request("DELETE", f"/api/boards/{board_id}")
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected delete_board response: {data}")
        return str(data["_id"])

    def create_list(self, *, board_id: str, title: str) -> str:
        backoff_seconds = 0.15
        for attempt in range(1, 4):
            try:
                data = self._request("POST", f"/api/boards/{board_id}/lists", json={"title": title})
                if not isinstance(data, dict) or "_id" not in data:
                    raise RuntimeError(f"Unexpected create_list response: {data}")
                return str(data["_id"])
            except NetworkError:
                recovered = self._recover_list_id_by_title(board_id=board_id, title=title, timeout_seconds=2.5, attempts=10)
                if recovered is not None:
                    return recovered
                if attempt < 3:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(0.6, backoff_seconds * 2)

        recovered = self._recover_list_id_by_title(board_id=board_id, title=title, timeout_seconds=5.0, attempts=16)
        if recovered is not None:
            return recovered
        raise NetworkError("Network error during list creation")


    def _recover_list_id_by_title(self, *, board_id: str, title: str, timeout_seconds: float, attempts: int) -> str | None:
        deadline = time.monotonic() + timeout_seconds
        for attempt in range(1, attempts + 1):
            try:
                lists = self.get_lists(board_id=board_id)
            except (NetworkError, HttpError):
                lists = []

            match = next((l for l in lists if l.get("title") == title and l.get("_id")), None)
            if match is not None:
                return str(match.get("_id") or "")

            remaining = deadline - time.monotonic()
            if attempt == attempts or remaining <= 0:
                break
            time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))
        return None

    def get_lists(self, *, board_id: str) -> list[dict[str, str]]:
        data = self._request("GET", f"/api/boards/{board_id}/lists")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_lists response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

    def get_list(self, *, board_id: str, list_id: str) -> dict[str, str]:
        data = self._request("GET", f"/api/boards/{board_id}/lists/{list_id}")
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected get_list response: {data}")
        return {k: str(v) for k, v in data.items()}

    def delete_list(self, *, board_id: str, list_id: str) -> str:
        data = self._request("DELETE", f"/api/boards/{board_id}/lists/{list_id}")
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected delete_list response: {data}")
        return str(data["_id"])

    def create_card(
        self,
        *,
        board_id: str,
        list_id: str,
        swimlane_id: str,
        title: str,
        description: str = "",
    ) -> str:
        payload = {
            "title": title,
            "description": description,
            "authorId": self.auth.user_id,
            "swimlaneId": swimlane_id,
        }
        backoff_seconds = 0.15
        for attempt in range(1, 4):
            try:
                data = self._request("POST", f"/api/boards/{board_id}/lists/{list_id}/cards", json=payload)
                if not isinstance(data, dict) or "_id" not in data:
                    raise RuntimeError(f"Unexpected create_card response: {data}")
                return str(data["_id"])
            except NetworkError:
                recovered = self._recover_card_id_by_title(board_id=board_id, list_id=list_id, title=title, timeout_seconds=2.5, attempts=10)
                if recovered is not None:
                    return recovered
                if attempt < 3:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(0.6, backoff_seconds * 2)

        recovered = self._recover_card_id_by_title(board_id=board_id, list_id=list_id, title=title, timeout_seconds=5.0, attempts=16)
        if recovered is not None:
            return recovered
        raise NetworkError("Network error during card creation")


    def _recover_card_id_by_title(
        self,
        *,
        board_id: str,
        list_id: str,
        title: str,
        timeout_seconds: float,
        attempts: int,
    ) -> str | None:
        deadline = time.monotonic() + timeout_seconds
        for attempt in range(1, attempts + 1):
            try:
                cards = self.get_list_cards(board_id=board_id, list_id=list_id)
            except (NetworkError, HttpError):
                cards = []

            match = next((c for c in cards if c.get("title") == title and c.get("_id")), None)
            if match is not None:
                return str(match.get("_id") or "")

            remaining = deadline - time.monotonic()
            if attempt == attempts or remaining <= 0:
                break
            time.sleep(min(0.25, max(0.0, remaining / max(1, (attempts - attempt)))))
        return None

    def get_swimlanes(self, *, board_id: str) -> list[dict[str, str]]:
        data = self._request("GET", f"/api/boards/{board_id}/swimlanes")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_swimlanes response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

    def delete_card(self, *, board_id: str, list_id: str, card_id: str) -> str:
        payload = {"authorId": self.auth.user_id}
        data = self._request(
            "DELETE",
            f"/api/boards/{board_id}/lists/{list_id}/cards/{card_id}",
            json=payload,
        )
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected delete_card response: {data}")
        return str(data["_id"])

    def get_user_boards(self, *, user_id: str | None = None) -> list[dict[str, str]]:
        user_id = user_id or self.auth.user_id
        data = self._request("GET", f"/api/users/{user_id}/boards")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_user_boards response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

    def get_swimlane_cards(self, *, board_id: str, swimlane_id: str) -> list[dict[str, str]]:
        data = self._request("GET", f"/api/boards/{board_id}/swimlanes/{swimlane_id}/cards")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_swimlane_cards response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

    def get_list_cards(self, *, board_id: str, list_id: str) -> list[dict[str, str]]:
        data = self._request("GET", f"/api/boards/{board_id}/lists/{list_id}/cards")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_list_cards response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

    def get_card(self, *, board_id: str, list_id: str, card_id: str) -> dict[str, str] | None:
        data = self._request("GET", f"/api/boards/{board_id}/lists/{list_id}/cards/{card_id}")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected get_card response: {data}")
        return {k: str(v) for k, v in data.items()}

    def get_card_global(self, *, card_id: str) -> dict[str, str]:
        data = self._request("GET", f"/api/cards/{card_id}")
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected get_card_global response: {data}")
        return {k: str(v) for k, v in data.items()}

    def update_card(
        self,
        *,
        board_id: str,
        list_id: str,
        card_id: str,
        swimlane_id: str,
        title: str | None = None,
        description: str | None = None,
        new_list_id: str | None = None,
    ) -> dict[str, str]:
        # Wekan API docs list multipart/form-data and mark newBoardId/newSwimlaneId/newListId as required.
        # In practice, sending JSON works on typical deployments.
        effective_list_id = new_list_id or list_id
        payload: dict[str, str] = {
            "authorId": self.auth.user_id,
            "swimlaneId": swimlane_id,
            "listId": effective_list_id,
            "newBoardId": board_id,
            "newSwimlaneId": swimlane_id,
            "newListId": effective_list_id,
        }
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description

        data = self._request("PUT", f"/api/boards/{board_id}/lists/{list_id}/cards/{card_id}", json=payload)
        if not isinstance(data, dict) or ("_id" not in data and "id" not in data):
            raise RuntimeError(f"Unexpected update_card response: {data}")
        return {k: str(v) for k, v in data.items()}
