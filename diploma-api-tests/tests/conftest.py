from __future__ import annotations

import sys
from pathlib import Path

# When running via `pytest.exe` on Windows, sys.path[0] can be the Scripts folder.
# Add the project root so imports like `diploma_tests.*` work reliably.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from diploma_tests.config import Settings
from diploma_tests.client import NetworkError, WekanClient
import uuid


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def client(settings: Settings) -> WekanClient:
    return WekanClient.from_settings(settings)


@pytest.fixture(scope="session")
def client2(settings: Settings) -> WekanClient:
    if not settings.has_second_login_credentials:
        pytest.skip("Second test user is not configured (set WEKAN_USERNAME_2/WEKAN_EMAIL_2 and WEKAN_PASSWORD_2)")

    client = WekanClient(settings.base_url, timeout_seconds=settings.timeout_seconds)
    try:
        client.login(username=settings.username2, email=settings.email2, password=settings.password2 or "")
    except NetworkError:
        pytest.skip("Wekan is not reachable for second-user login")
    return client


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
        # Do not retry POST globally. Keep status retries for safe methods only.
        allowed_methods=("GET", "PUT", "DELETE"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Keep base_url on the session for convenience in tests.
    session.base_url = settings.base_url  # type: ignore[attr-defined]
    session.timeout_seconds = settings.timeout_seconds  # type: ignore[attr-defined]
    return session


@pytest.fixture()
def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]
