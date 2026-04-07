from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field


# Extracts the major parameter (channel_id or guild_id) from an endpoint.
# Discord scopes rate limits by (method, major_param).
_MAJOR_PARAM_RE = re.compile(r"^/(channels|guilds|users)/([^/]+)")


def route_key(method: str, endpoint: str) -> str:
    """Derive a rate limit route key from an HTTP method and endpoint path.

    Examples:
        DELETE /channels/123/messages/456 -> "DELETE:channels:123"
        GET /guilds/789/messages/search   -> "GET:guilds:789"
        GET /users/@me/guilds             -> "GET:users:@me"
    """
    m = _MAJOR_PARAM_RE.match(endpoint)
    if m:
        return f"{method}:{m.group(1)}:{m.group(2)}"
    return f"{method}:{endpoint}"


@dataclass(slots=True)
class BucketState:
    bucket_id: str
    remaining: int
    reset_at: float  # time.monotonic() based
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class _TokenBucket:
    """Global requests-per-second limiter using a token bucket algorithm."""

    def __init__(self, rate: int) -> None:
        self._rate = float(rate)
        self._tokens = float(rate)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1.0


class RateLimiter:
    """Three-layer rate limiter for Discord API requests.

    Layer 1: Global token bucket (~global_rps requests/second)
    Layer 2: Global 429 pause (when X-RateLimit-Scope: global)
    Layer 3: Per-route bucket tracking from X-RateLimit-* headers
    """

    def __init__(self, global_rps: int = 45) -> None:
        self._token_bucket = _TokenBucket(global_rps)
        self._buckets: dict[str, BucketState] = {}
        self._route_to_bucket: dict[str, str] = {}
        self._global_paused_until: float = 0.0
        self.preemptive_waits: int = 0
        self.global_pauses: int = 0

    async def acquire(self, rkey: str) -> None:
        """Wait until this route has capacity. Call before every request."""
        # Layer 1: global RPS
        await self._token_bucket.acquire()

        # Layer 2: global 429 pause
        now = time.monotonic()
        if self._global_paused_until > now:
            self.global_pauses += 1
            await asyncio.sleep(self._global_paused_until - now)

        # Layer 3: per-route bucket
        bucket_id = self._route_to_bucket.get(rkey)
        if bucket_id is None:
            return

        bucket = self._buckets.get(bucket_id)
        if bucket is None:
            return

        async with bucket.lock:
            now = time.monotonic()
            if bucket.remaining <= 0 and bucket.reset_at > now:
                self.preemptive_waits += 1
                await asyncio.sleep(bucket.reset_at - now)

    def update(self, rkey: str, headers: dict[str, str]) -> None:
        """Update bucket state from response headers. Call after every response."""
        bucket_id = headers.get("X-RateLimit-Bucket")
        if bucket_id is None:
            return

        remaining_str = headers.get("X-RateLimit-Remaining")
        reset_after_str = headers.get("X-RateLimit-Reset-After")

        if remaining_str is None or reset_after_str is None:
            return

        try:
            remaining = int(remaining_str)
            reset_after = float(reset_after_str)
        except (ValueError, TypeError):
            return

        reset_at = time.monotonic() + reset_after

        self._route_to_bucket[rkey] = bucket_id

        if bucket_id in self._buckets:
            bucket = self._buckets[bucket_id]
            bucket.remaining = remaining
            bucket.reset_at = reset_at
        else:
            self._buckets[bucket_id] = BucketState(
                bucket_id=bucket_id,
                remaining=remaining,
                reset_at=reset_at,
            )

    async def handle_429(self, rkey: str, retry_after: float, is_global: bool) -> None:
        """Handle a 429 response. Sleep for retry_after seconds."""
        if is_global:
            self._global_paused_until = time.monotonic() + retry_after
        await asyncio.sleep(retry_after)
