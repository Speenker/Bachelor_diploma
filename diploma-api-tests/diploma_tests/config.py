from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str | None
    email: str | None
    password: str | None
    timeout_seconds: float

    @property
    def has_login_credentials(self) -> bool:
        return bool(self.password and (self.username or self.email))

    @staticmethod
    def from_env() -> "Settings":
        # Loads .env if present; environment variables still override it.
        load_dotenv(override=False)

        base_url = (os.getenv("BASE_URL") or "http://localhost").rstrip("/")
        username = os.getenv("WEKAN_USERNAME") or None
        email = os.getenv("WEKAN_EMAIL") or None
        password = os.getenv("WEKAN_PASSWORD") or None
        timeout_seconds = float(os.getenv("REQUEST_TIMEOUT_SECONDS") or "20")

        return Settings(
            base_url=base_url,
            username=username,
            email=email,
            password=password,
            timeout_seconds=timeout_seconds,
        )
