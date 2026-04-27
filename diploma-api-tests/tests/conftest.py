from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from diploma_tests.config import Settings
from diploma_tests.client import HttpError, NetworkError, WekanClient
import uuid


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if call.excinfo is not None and call.excinfo.errisinstance(NetworkError):
        rep.outcome = "skipped"
        reason = f"Wekan is not reachable ({call.excinfo.value})"
        file_name, line_no, _ = item.location
        rep.longrepr = (file_name, line_no, reason)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def client(settings: Settings) -> WekanClient:
    try:
        return WekanClient.from_settings(settings)
    except NetworkError as exc:
        pytest.skip(f"Wekan is not reachable for login ({exc})")


@pytest.fixture(scope="session")
def client2(settings: Settings) -> WekanClient:
    if not settings.has_second_login_credentials:
        pytest.skip("Second test user is not configured (set WEKAN_USERNAME_2/WEKAN_EMAIL_2 and WEKAN_PASSWORD_2)")

    client = WekanClient(settings.base_url, timeout_seconds=settings.timeout_seconds)
    backoff_seconds = 0.2
    last_network_error: NetworkError | None = None
    for attempt in range(1, 9):
        try:
            client.login(username=settings.username2, email=settings.email2, password=settings.password2 or "")
            return client
        except NetworkError as exc:
            last_network_error = exc
            if attempt < 8:
                time.sleep(min(2.0, backoff_seconds))
                backoff_seconds *= 2
                continue
            pytest.skip(f"Wekan is not reachable for second-user login ({exc})")
        except HttpError as exc:
            body = exc.body
            if isinstance(body, dict) and body.get("error") == "not-found":
                pytest.skip(
                    "Second test user credentials are configured, but the user does not exist on the Wekan server. "
                    "Create the user in Wekan UI (or enable /users/register) and re-run."
                )
            pytest.skip(
                "Second test user login was rejected. Check WEKAN_USERNAME_2/WEKAN_EMAIL_2 and WEKAN_PASSWORD_2. "
                f"Server returned {exc.status_code}."
            )

    pytest.skip(f"Wekan is not reachable for second-user login ({last_network_error})")


@pytest.fixture(scope="session")
def http_session(settings: Settings) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=False,
        read=False,
        status=3,
        backoff_factor=0.25,
        status_forcelist=(502, 503, 504),
        allowed_methods=("GET", "PUT", "DELETE"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.base_url = settings.base_url
    session.timeout_seconds = settings.timeout_seconds
    return session


@pytest.fixture()
def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]
