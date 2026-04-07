from __future__ import annotations


class DiscordAPIError(Exception):
    """Base for all Discord API errors. Carries full request context."""

    def __init__(self, endpoint: str, status: int, body: str) -> None:
        self.endpoint = endpoint
        self.status = status
        self.body = body
        super().__init__(f"[{status}] {endpoint}: {body[:200]}")


class AuthenticationError(DiscordAPIError):
    """401 — token is invalid or expired. Abort everything."""


class ResourceUnavailable(DiscordAPIError):
    """403 or 404 — resource inaccessible or already deleted. Caller skips."""


class RateLimitExceeded(DiscordAPIError):
    """429 after exhausting max retries."""


class UnexpectedStatus(DiscordAPIError):
    """Any non-success status not covered by the above."""
