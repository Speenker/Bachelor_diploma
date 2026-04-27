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
    username2: str | None
    email2: str | None
    password2: str | None
    timeout_seconds: float

    @property
    def has_login_credentials(self) -> bool:
        return bool(self.password and (self.username or self.email))

    @property
    def has_second_login_credentials(self) -> bool:
        return bool(self.password2 and (self.username2 or self.email2))

    @staticmethod
    def from_env() -> "Settings":
        load_dotenv(override=False)

        base_url = (os.getenv("BASE_URL") or "http://localhost").rstrip("/")
        username = os.getenv("WEKAN_USERNAME") or None
        email = os.getenv("WEKAN_EMAIL") or None
        password = os.getenv("WEKAN_PASSWORD") or None

        username2 = os.getenv("WEKAN_USERNAME_2") or None
        email2 = os.getenv("WEKAN_EMAIL_2") or None
        password2 = os.getenv("WEKAN_PASSWORD_2") or None
        timeout_seconds = float(os.getenv("REQUEST_TIMEOUT_SECONDS") or "20")

        return Settings(
            base_url=base_url,
            username=username,
            email=email,
            password=password,
            username2=username2,
            email2=email2,
            password2=password2,
            timeout_seconds=timeout_seconds,
        )
