from __future__ import annotations

import time
from types import SimpleNamespace

import aiohttp
import aioresponses.core as aioresponses_core
import pytest
from aioresponses import aioresponses


class _MockClientResponse(aiohttp.ClientResponse):
    """aiohttp 3.14 made ClientResponse's stream_writer argument required, and
    aioresponses 0.7.9 doesn't pass it yet. Mocked responses never upload a
    body, so stand in a writer that reports nothing sent. Drop this once
    aioresponses supports aiohttp 3.14."""

    def __init__(self, *args, stream_writer=None, **kwargs):
        if stream_writer is None:
            stream_writer = SimpleNamespace(output_size=0)
        super().__init__(*args, stream_writer=stream_writer, **kwargs)


aioresponses_core.ClientResponse = _MockClientResponse

BASE_URL = "https://discord.com/api/v10"

MOCK_USER = {"id": "123456789012345678", "username": "testuser", "discriminator": "0"}


@pytest.fixture
def mock_api():
    with aioresponses() as m:
        yield m


def discord_url(endpoint: str) -> str:
    return f"{BASE_URL}{endpoint}"


def rate_limit_headers(
    bucket: str = "test-bucket",
    remaining: int = 10,
    reset_after: float = 5.0,
    limit: int = 10,
) -> dict[str, str]:
    return {
        "X-RateLimit-Bucket": bucket,
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset-After": str(reset_after),
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Reset": str(time.time() + reset_after),
    }
