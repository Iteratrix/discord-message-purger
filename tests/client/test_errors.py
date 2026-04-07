import pytest

from discord_purger.client.errors import (
    AuthenticationError,
    DiscordAPIError,
    RateLimitExceeded,
    ResourceUnavailable,
    UnexpectedStatus,
)


def test_discord_api_error_fields():
    e = DiscordAPIError("/users/@me", 500, "Internal Server Error")
    assert e.endpoint == "/users/@me"
    assert e.status == 500
    assert e.body == "Internal Server Error"


def test_discord_api_error_str():
    e = DiscordAPIError("/test", 400, "Bad Request")
    assert "[400]" in str(e)
    assert "/test" in str(e)
    assert "Bad Request" in str(e)


def test_body_truncated_in_str():
    long_body = "x" * 500
    e = DiscordAPIError("/test", 400, long_body)
    assert len(str(e)) < 300  # truncated to 200 chars of body


def test_authentication_error_is_discord_api_error():
    e = AuthenticationError("/users/@me", 401, "Unauthorized")
    assert isinstance(e, DiscordAPIError)
    assert isinstance(e, Exception)
    assert e.status == 401


def test_resource_unavailable_catchable():
    with pytest.raises(ResourceUnavailable) as exc_info:
        raise ResourceUnavailable("/channels/123", 403, "Forbidden")
    assert exc_info.value.status == 403


def test_resource_unavailable_404():
    e = ResourceUnavailable("/channels/123/messages/456", 404, "Not Found")
    assert e.status == 404
    assert "456" in e.endpoint


def test_rate_limit_exceeded():
    e = RateLimitExceeded("/channels/123/messages", 429, "Rate limited")
    assert isinstance(e, DiscordAPIError)
    assert e.status == 429


def test_unexpected_status():
    e = UnexpectedStatus("/test", 418, "I'm a teapot")
    assert isinstance(e, DiscordAPIError)
    assert e.status == 418


def test_all_errors_catchable_as_base():
    for cls in (AuthenticationError, ResourceUnavailable, RateLimitExceeded, UnexpectedStatus):
        try:
            raise cls("/test", 999, "test")
        except DiscordAPIError as e:
            assert e.status == 999
