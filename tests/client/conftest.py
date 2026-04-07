from __future__ import annotations

import time

import pytest
from aioresponses import aioresponses

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
