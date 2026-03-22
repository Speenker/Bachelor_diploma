from __future__ import annotations

import time
from typing import Any


def _redact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    safe_kwargs: dict[str, Any] = dict(kwargs)
    headers = safe_kwargs.get("headers")
    if isinstance(headers, dict):
        safe_headers = dict(headers)
        if "Authorization" in safe_headers:
            safe_headers["Authorization"] = "<redacted>"
        safe_kwargs["headers"] = safe_headers
    return safe_kwargs


def request_with_network_retry(
    session: Any,
    method: str,
    url: str,
    *,
    attempts: int = 6,
    backoff_base_seconds: float = 0.1,
    backoff_cap_seconds: float = 0.5,
    **kwargs: Any,
):
    """Perform an HTTP request with a small retry loop for transient network errors.

    Purpose
    - Stabilize test runs in local environments where the server can occasionally
      reset/abort connections.

    Notes
    - Retries are triggered only on exceptions thrown by the underlying request
      call.
    - This helper does not retry based on HTTP status codes.
    """

    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return session.request(method, url, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                sleep_seconds = min(backoff_cap_seconds, backoff_base_seconds * (2**attempt))
                time.sleep(sleep_seconds)

    kwargs = _redact_kwargs(kwargs)
    raise AssertionError(f"Network error calling {method} {url}: {last_exc}")


def is_wekan_unauthorized(*, status_code: int, body: object) -> bool:
    """Return True if the response represents an unauthorized error in Wekan.

    Wekan may respond in two forms:
    - HTTP 401 or 403
    - HTTP 200 with an error object in JSON, e.g. {"error":"Unauthorized", "statusCode":401}
    """

    if status_code in (401, 403):
        return True

    if not isinstance(body, dict):
        return False

    if body.get("error") == "Unauthorized":
        return True

    status = body.get("status") or body.get("statusCode")
    try:
        return int(status) in (401, 403)
    except Exception:
        return False
