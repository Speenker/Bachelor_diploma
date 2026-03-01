from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings


@dataclass
class Auth:
    user_id: str
    token: str


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
        attempts = 3 if method_upper in safe_methods else 1

        if attempts == 1:
            resp = self.session.request(
                method_upper,
                self._url(path),
                headers=self._headers(),
                json=json,
                timeout=self.timeout_seconds,
            )
        else:
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
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                    last_exc = exc
                    if attempt + 1 < attempts:
                        time.sleep(0.25 * (2**attempt))

            if resp is None:
                raise RuntimeError(f"{method_upper} {path} failed after retries: {last_exc}")

        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = resp.text

        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} failed: {resp.status_code} {data}")
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
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                if attempt < 4:
                    # 0.1s, 0.2s, 0.4s, 0.8s
                    time.sleep(0.1 * (2**attempt))

        if data is None:
            raise RuntimeError(f"POST /users/login failed after retries: {last_exc}")
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
        data = self._request("POST", "/api/boards", json=payload)
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected create_board response: {data}")
        return {k: str(v) for k, v in data.items()}

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
        data = self._request("POST", f"/api/boards/{board_id}/lists", json={"title": title})
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected create_list response: {data}")
        return str(data["_id"])

    def get_lists(self, *, board_id: str) -> list[dict[str, str]]:
        data = self._request("GET", f"/api/boards/{board_id}/lists")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected get_lists response: {data}")
        return [{k: str(v) for k, v in item.items()} for item in data if isinstance(item, dict)]

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
        data = self._request("POST", f"/api/boards/{board_id}/lists/{list_id}/cards", json=payload)
        if not isinstance(data, dict) or "_id" not in data:
            raise RuntimeError(f"Unexpected create_card response: {data}")
        return str(data["_id"])

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
