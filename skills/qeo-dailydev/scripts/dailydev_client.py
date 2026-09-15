from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://api.daily.dev/public/v1"
VALID_TIME_RANGES = {"day", "week", "month", "year", "all"}


class DailyDevError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, endpoint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.endpoint = endpoint


class DailyDevClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], Any] | None = None,
    ) -> None:
        token = token.strip()
        if not token:
            raise ValueError("daily.dev token is required")
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self._opener = opener or urlopen
        self._sleep = sleeper or time.sleep

    def get_for_you(self, *, limit: int = 20, cursor: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": self._bounded_limit(limit, 50)}
        if cursor:
            params["cursor"] = cursor
        return self._get("/feeds/foryou", params)

    def recommend_keyword(
        self,
        query: str,
        *,
        limit: int = 10,
        time_range: str = "month",
        cursor: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "q": self._query(query),
            "limit": self._bounded_limit(limit, 20),
            "time": self._time_range(time_range),
        }
        if cursor:
            params["cursor"] = cursor
        return self._get("/recommend/keyword", params)

    def recommend_semantic(
        self,
        query: str,
        *,
        limit: int = 10,
        time_range: str = "month",
    ) -> dict:
        return self._get(
            "/recommend/semantic",
            {
                "q": self._query(query),
                "limit": self._bounded_limit(limit, 20),
                "time": self._time_range(time_range),
            },
        )

    def get_post(self, post_id: str) -> dict:
        value = str(post_id).strip()
        if not value:
            raise ValueError("post_id is required")
        return self._get(f"/posts/{quote(value, safe='')}", None)

    @staticmethod
    def _query(query: str) -> str:
        value = str(query).strip()
        if not value:
            raise ValueError("query is required")
        return value

    @staticmethod
    def _bounded_limit(limit: int, maximum: int) -> int:
        value = int(limit)
        if value < 1 or value > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        return value

    @staticmethod
    def _time_range(value: str) -> str:
        if value not in VALID_TIME_RANGES:
            raise ValueError(f"time_range must be one of {sorted(VALID_TIME_RANGES)}")
        return value

    def _get(self, path: str, params: dict[str, Any] | None) -> dict:
        query = urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "qeo-dailydev/1.0",
            },
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = self._opener(request, timeout=self.timeout)
                try:
                    payload = response.read()
                finally:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                try:
                    decoded = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DailyDevError(
                        f"daily.dev returned invalid JSON for {path}", endpoint=path
                    ) from exc
                if not isinstance(decoded, dict):
                    raise DailyDevError(
                        f"daily.dev returned unexpected JSON for {path}", endpoint=path
                    )
                return decoded
            except HTTPError as exc:
                if exc.code == 401:
                    raise DailyDevError(
                        f"daily.dev authentication failed for {path}",
                        status=401,
                        endpoint=path,
                    ) from exc
                if exc.code == 429 and attempt < self.max_retries:
                    self._sleep(self._retry_after(exc))
                    continue
                if 500 <= exc.code < 600 and attempt < self.max_retries:
                    self._sleep(float(2**attempt))
                    continue
                raise DailyDevError(
                    f"daily.dev request failed for {path} (HTTP {exc.code})",
                    status=exc.code,
                    endpoint=path,
                ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    self._sleep(float(2**attempt))
                    continue
                raise DailyDevError(
                    f"daily.dev request failed for {path}", endpoint=path
                ) from exc

        raise DailyDevError(f"daily.dev request failed for {path}", endpoint=path)

    @staticmethod
    def _retry_after(exc: HTTPError) -> float:
        raw = None
        headers = getattr(exc, "headers", None)
        if headers is not None:
            raw = headers.get("Retry-After")
        try:
            value = float(raw) if raw is not None else 1.0
        except (TypeError, ValueError):
            value = 1.0
        return min(60.0, max(0.0, value))
