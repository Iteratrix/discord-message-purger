from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import aiohttp

from .errors import (
    AuthenticationError,
    RateLimitExceeded,
    ResourceUnavailable,
    UnexpectedStatus,
)
from .rate_limit import RateLimiter, route_key


class HTTPClient:
    """Low-level async HTTP client for the Discord REST API v10.

    Handles rate limiting, retries, and error classification.
    All high-level methods in DiscordClient delegate to this.
    """

    BASE_URL = "https://discord.com/api/v10"

    def __init__(
        self,
        token: str,
        *,
        max_retries: int = 5,
        retry_buffer: tuple[float, float] = (1.0, 3.0),
        global_rps: int = 45,
    ) -> None:
        self._token = token
        self._max_retries = max_retries
        self._retry_buffer = retry_buffer
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(global_rps)
        self.rate_limit_hits: int = 0
        self.server_errors: int = 0
        self.network_errors: int = 0

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": self._token,
            },
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> tuple[int, Any]:
        """Execute a request with rate limiting and retry logic.

        Returns (status_code, parsed_json_body).
        Body is None for 204 responses.
        """
        assert self._session is not None, "HTTPClient not started. Call start() first."

        url = f"{self.BASE_URL}{endpoint}"
        rkey = route_key(method, endpoint)

        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.acquire(rkey)

            try:
                kwargs: dict[str, Any] = {"params": params}
                if json_body is not None:
                    kwargs["json"] = json_body
                async with self._session.request(method, url, **kwargs) as resp:
                    status = resp.status
                    headers = {k: v for k, v in resp.headers.items()}
                    body_text = await resp.text()

                    # Always update rate limit state
                    self._rate_limiter.update(rkey, headers)

                    if status in (200, 204):
                        data = json.loads(body_text) if body_text else None
                        return status, data

                    elif status == 429:
                        self.rate_limit_hits += 1
                        try:
                            body = json.loads(body_text) if body_text else {}
                        except json.JSONDecodeError:
                            body = {}
                        retry_after = float(body.get("retry_after", 1.0))
                        is_global = headers.get("X-RateLimit-Scope") == "global"
                        buffer = random.uniform(*self._retry_buffer)
                        await self._rate_limiter.handle_429(
                            rkey, retry_after + buffer, is_global,
                        )
                        continue

                    elif status >= 500:
                        self.server_errors += 1
                        buffer = random.uniform(*self._retry_buffer)
                        await asyncio.sleep(buffer * (attempt + 1))
                        continue

                    elif status == 401:
                        raise AuthenticationError(endpoint, status, body_text)

                    elif status in (400, 403, 404):
                        raise ResourceUnavailable(endpoint, status, body_text)

                    else:
                        raise UnexpectedStatus(endpoint, status, body_text)

            except (TimeoutError, aiohttp.ClientError):
                self.network_errors += 1
                if attempt < self._max_retries:
                    buffer = random.uniform(*self._retry_buffer)
                    await asyncio.sleep(buffer * (attempt + 1))
                    continue
                raise RateLimitExceeded(endpoint, 0, "Network error after max retries")

        raise RateLimitExceeded(endpoint, 429, "Max retries exceeded")
