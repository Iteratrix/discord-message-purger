import pytest

from discord_purger.client.errors import (
    AuthenticationError,
    RateLimitExceeded,
    ResourceUnavailable,
    UnexpectedStatus,
)
from discord_purger.client.http import HTTPClient

from .conftest import MOCK_USER, discord_url, rate_limit_headers


@pytest.fixture
async def http_client():
    client = HTTPClient("test-token", max_retries=2, retry_buffer=(0.01, 0.02), global_rps=100)
    await client.start()
    yield client
    await client.close()


async def test_successful_get(mock_api, http_client):
    mock_api.get(
        discord_url("/users/@me"),
        payload=MOCK_USER,
        headers=rate_limit_headers(),
    )
    status, data = await http_client.request("GET", "/users/@me")
    assert status == 200
    assert data["id"] == "123456789012345678"


async def test_successful_delete_204(mock_api, http_client):
    mock_api.delete(
        discord_url("/channels/123/messages/456"),
        status=204,
        headers=rate_limit_headers(),
    )
    status, data = await http_client.request("DELETE", "/channels/123/messages/456")
    assert status == 204
    assert data is None


async def test_401_raises_authentication_error(mock_api, http_client):
    mock_api.get(
        discord_url("/users/@me"),
        status=401,
        body="Unauthorized",
        headers=rate_limit_headers(),
    )
    with pytest.raises(AuthenticationError) as exc_info:
        await http_client.request("GET", "/users/@me")
    assert exc_info.value.status == 401


async def test_403_raises_resource_unavailable(mock_api, http_client):
    mock_api.delete(
        discord_url("/channels/123/messages/456"),
        status=403,
        body="Forbidden",
        headers=rate_limit_headers(),
    )
    with pytest.raises(ResourceUnavailable) as exc_info:
        await http_client.request("DELETE", "/channels/123/messages/456")
    assert exc_info.value.status == 403


async def test_404_raises_resource_unavailable(mock_api, http_client):
    mock_api.delete(
        discord_url("/channels/123/messages/456"),
        status=404,
        body="Not Found",
        headers=rate_limit_headers(),
    )
    with pytest.raises(ResourceUnavailable):
        await http_client.request("DELETE", "/channels/123/messages/456")


async def test_429_retries(mock_api, http_client):
    url = discord_url("/channels/123/messages/456")
    # First call: 429
    mock_api.delete(
        url,
        status=429,
        payload={"retry_after": 0.01},
        headers=rate_limit_headers(remaining=0, reset_after=0.01),
    )
    # Second call: success
    mock_api.delete(
        url,
        status=204,
        headers=rate_limit_headers(),
    )
    status, data = await http_client.request("DELETE", "/channels/123/messages/456")
    assert status == 204


async def test_429_max_retries_raises(mock_api, http_client):
    url = discord_url("/channels/123/messages/456")
    # All attempts return 429
    for _ in range(3):  # max_retries=2, so 3 total attempts
        mock_api.delete(
            url,
            status=429,
            payload={"retry_after": 0.01},
            headers=rate_limit_headers(remaining=0, reset_after=0.01),
        )
    with pytest.raises(RateLimitExceeded):
        await http_client.request("DELETE", "/channels/123/messages/456")


async def test_5xx_retries(mock_api, http_client):
    url = discord_url("/users/@me")
    # First: 500
    mock_api.get(url, status=500, body="Internal Server Error", headers=rate_limit_headers())
    # Second: success
    mock_api.get(url, payload=MOCK_USER, headers=rate_limit_headers())

    status, data = await http_client.request("GET", "/users/@me")
    assert status == 200


async def test_5xx_max_retries_raises(mock_api, http_client):
    url = discord_url("/users/@me")
    for _ in range(3):
        mock_api.get(url, status=500, body="Error", headers=rate_limit_headers())
    with pytest.raises(RateLimitExceeded):
        await http_client.request("GET", "/users/@me")


async def test_unexpected_status_raises(mock_api, http_client):
    mock_api.get(
        discord_url("/users/@me"),
        status=418,
        body="I'm a teapot",
        headers=rate_limit_headers(),
    )
    with pytest.raises(UnexpectedStatus) as exc_info:
        await http_client.request("GET", "/users/@me")
    assert exc_info.value.status == 418


async def test_params_passed_to_request(mock_api, http_client):
    mock_api.get(
        discord_url("/guilds/789/messages/search?author_id=123&offset=0"),
        payload={"messages": [], "total_results": 0},
        headers=rate_limit_headers(),
    )
    status, data = await http_client.request(
        "GET", "/guilds/789/messages/search",
        params={"author_id": "123", "offset": "0"},
    )
    assert status == 200
    assert data["total_results"] == 0


async def test_rate_limit_headers_update_state(mock_api, http_client):
    mock_api.get(
        discord_url("/users/@me"),
        payload=MOCK_USER,
        headers=rate_limit_headers(bucket="my-bucket", remaining=3, reset_after=2.0),
    )
    await http_client.request("GET", "/users/@me")
    # Verify bucket was tracked
    assert "my-bucket" in http_client._rate_limiter._buckets
    assert http_client._rate_limiter._buckets["my-bucket"].remaining == 3
