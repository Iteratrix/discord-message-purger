# Module 2: Async Discord API Client

## Purpose

Provide a low-level async HTTP client for the Discord REST API v10 with proper per-route rate limiting, retry logic, and error handling. This is the foundation that the search sweep and deletion engine build on.

## Design Principles

- **Async-native**: built on `aiohttp`, all methods are coroutines
- **Rate-limit-aware**: track per-route buckets using `X-RateLimit-*` response headers, sleep proactively when a bucket is exhausted rather than waiting for 429s
- **Resilient**: retry on 429 and 5xx with backoff, skip on 403/404, fail fast on 401
- **Concurrent but controlled**: expose semaphores/limits so callers can fan out across channels without blowing the global rate limit

## Authentication

- Accept a Discord user token (not bot token)
- Send as `Authorization: <token>` header (no prefix)
- Validate on startup by calling `GET /users/@me`
- Fail fast with clear error if 401

## Endpoints to Support

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/users/@me` | Resolve current user ID |
| GET | `/users/@me/guilds` | List all guilds (paginated, 200/page) |
| GET | `/guilds/{guild_id}/channels` | List channels in a guild |
| GET | `/users/@me/channels` | List DM/group DM channels |
| GET | `/guilds/{guild_id}/messages/search?author_id={id}` | Search user's messages in a guild |
| GET | `/channels/{channel_id}/messages/search?author_id={id}` | Search user's messages in a DM/group DM |
| DELETE | `/channels/{channel_id}/messages/{message_id}` | Delete a single message |
| DELETE | `/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me` | Remove own reaction |

## Rate Limiting

### Per-Route Tracking

Discord returns rate limit info in response headers:

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Bucket` | Opaque bucket identifier (shared across routes) |
| `X-RateLimit-Limit` | Max requests in the current window |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | Unix timestamp (float) when the bucket resets |
| `X-RateLimit-Reset-After` | Seconds (float) until reset |

Strategy:
- Maintain a dict of bucket → reset time + remaining count
- Before each request, check if the route's bucket is exhausted; if so, sleep until reset
- After each request, update the bucket from response headers
- This avoids most 429s proactively

### 429 Handling (Fallback)

When a 429 is received despite proactive tracking:
- Parse `retry_after` from the response JSON body
- Add a small random buffer (1-3 seconds, not the 25-35s that delete-me-discord uses)
- Check if `X-RateLimit-Scope` is `global` — if so, pause ALL requests, not just this route
- Retry after sleeping

### Global Rate Limit

- Discord enforces 50 requests/second globally
- Use a global semaphore or token bucket to enforce this ceiling across all concurrent operations

### Configurable Defaults

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `delete_delay` | `(0.5, 1.0)` seconds | Random sleep between deletes (on top of rate limit waits) — provides headroom and humanization |
| `fetch_delay` | `(0.1, 0.3)` seconds | Random sleep between fetches |
| `retry_buffer` | `(1.0, 3.0)` seconds | Buffer added to `retry_after` on 429 |
| `max_retries` | 5 | Max retries before giving up on a request |
| `max_concurrency` | 10 | Max concurrent channels being processed |
| `global_rps` | 45 | Global requests/second ceiling (under the 50 hard limit) |

## Error Handling

| Status | Behavior |
|--------|----------|
| 200, 204 | Success |
| 429 | Retry after `retry_after` + buffer (see above) |
| 5xx | Retry with exponential backoff (1s, 2s, 4s...) up to max_retries |
| 401 | Raise `AuthenticationError`, abort everything |
| 403 | Raise `ResourceUnavailable` — caller decides to skip or retry |
| 404 | Raise `ResourceUnavailable` — message/channel already deleted or inaccessible |
| Other | Raise `UnexpectedStatus` with status code and body |

All errors should include the endpoint, status code, and response body in the exception for debugging.

## Interface Sketch

```python
class DiscordClient:
    def __init__(self, token: str, **config):
        ...

    async def get_current_user(self) -> dict:
        ...

    async def get_guilds(self) -> list[dict]:
        """Handles pagination for users in 200+ guilds."""
        ...

    async def get_guild_channels(self, guild_id: str) -> list[dict]:
        ...

    async def get_dm_channels(self) -> list[dict]:
        ...

    async def search_guild_messages(self, guild_id: str, author_id: str) -> AsyncIterator[dict]:
        """Yields messages matching author_id across the entire guild."""
        ...

    async def search_channel_messages(self, channel_id: str, author_id: str) -> AsyncIterator[dict]:
        """Yields messages matching author_id in a specific channel (for DMs)."""
        ...

    async def delete_message(self, channel_id: str, message_id: str) -> bool:
        """Returns True if deleted, False if skipped (403/404)."""
        ...

    async def delete_reaction(self, channel_id: str, message_id: str, emoji: str) -> bool:
        """Returns True if removed, False if skipped."""
        ...

    async def close(self):
        ...
```

## Testing Strategy

- Unit test rate limit tracking logic with mock headers
- Unit test retry/backoff behavior with mock responses
- Integration test against real Discord API (requires token, gated behind env var)
- Test guild pagination (mock 200+ guilds across multiple pages)
- Test global rate limit enforcement (verify requests don't exceed ceiling)

## Dependencies

- `aiohttp` — async HTTP client
- Standard library: `asyncio`, `time`, `random`, `urllib.parse`
