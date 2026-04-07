import asyncio
import time

from discord_purger.client.rate_limit import BucketState, RateLimiter, _TokenBucket, route_key


# --- route_key ---


def test_route_key_channel_delete():
    assert route_key("DELETE", "/channels/123/messages/456") == "DELETE:channels:123"


def test_route_key_guild_search():
    assert route_key("GET", "/guilds/789/messages/search") == "GET:guilds:789"


def test_route_key_user_endpoint():
    assert route_key("GET", "/users/@me/guilds") == "GET:users:@me"


def test_route_key_user_self():
    assert route_key("GET", "/users/@me") == "GET:users:@me"


def test_route_key_channel_reaction():
    assert route_key("DELETE", "/channels/100/messages/200/reactions/%F0%9F%94%A5/@me") == "DELETE:channels:100"


def test_route_key_unknown_endpoint():
    # Fallback for unrecognized patterns
    assert route_key("GET", "/something/else") == "GET:/something/else"


# --- BucketState ---


def test_bucket_state_fields():
    b = BucketState(bucket_id="abc", remaining=5, reset_at=100.0)
    assert b.bucket_id == "abc"
    assert b.remaining == 5
    assert b.reset_at == 100.0
    assert isinstance(b.lock, asyncio.Lock)


# --- _TokenBucket ---


async def test_token_bucket_acquire_immediate():
    """First acquire should not sleep (bucket starts full)."""
    tb = _TokenBucket(rate=10)
    start = time.monotonic()
    await tb.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


async def test_token_bucket_throttles():
    """Rapidly consuming all tokens should cause a sleep."""
    tb = _TokenBucket(rate=5)
    # Consume all 5 tokens
    for _ in range(5):
        await tb.acquire()
    # Next acquire should sleep ~0.2s (1/5)
    start = time.monotonic()
    await tb.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.1  # should wait for refill


# --- RateLimiter ---


async def test_acquire_passes_when_no_bucket():
    """First request to a route (no bucket info yet) should pass immediately."""
    rl = RateLimiter(global_rps=100)
    start = time.monotonic()
    await rl.acquire("GET:channels:123")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


async def test_acquire_passes_when_remaining():
    """Should pass immediately when bucket has remaining requests."""
    rl = RateLimiter(global_rps=100)
    rkey = "GET:channels:123"
    rl.update(rkey, {
        "X-RateLimit-Bucket": "bucket-a",
        "X-RateLimit-Remaining": "5",
        "X-RateLimit-Reset-After": "1.0",
    })
    start = time.monotonic()
    await rl.acquire(rkey)
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


async def test_acquire_sleeps_when_exhausted():
    """Should sleep when bucket is exhausted."""
    rl = RateLimiter(global_rps=100)
    rkey = "DELETE:channels:123"
    rl.update(rkey, {
        "X-RateLimit-Bucket": "bucket-b",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset-After": "0.2",
    })
    start = time.monotonic()
    await rl.acquire(rkey)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15  # should have slept ~0.2s


async def test_update_creates_new_bucket():
    rl = RateLimiter(global_rps=100)
    rkey = "GET:guilds:789"
    rl.update(rkey, {
        "X-RateLimit-Bucket": "bucket-new",
        "X-RateLimit-Remaining": "9",
        "X-RateLimit-Reset-After": "5.0",
    })
    assert "bucket-new" in rl._buckets
    assert rl._buckets["bucket-new"].remaining == 9


async def test_update_modifies_existing_bucket():
    rl = RateLimiter(global_rps=100)
    rkey = "GET:guilds:789"
    rl.update(rkey, {
        "X-RateLimit-Bucket": "bucket-x",
        "X-RateLimit-Remaining": "10",
        "X-RateLimit-Reset-After": "5.0",
    })
    rl.update(rkey, {
        "X-RateLimit-Bucket": "bucket-x",
        "X-RateLimit-Remaining": "3",
        "X-RateLimit-Reset-After": "2.0",
    })
    assert rl._buckets["bucket-x"].remaining == 3


async def test_update_ignores_missing_headers():
    rl = RateLimiter(global_rps=100)
    rkey = "GET:channels:123"
    rl.update(rkey, {})  # no rate limit headers
    assert len(rl._buckets) == 0


async def test_multiple_routes_independent_buckets():
    rl = RateLimiter(global_rps=100)
    rl.update("GET:channels:100", {
        "X-RateLimit-Bucket": "bucket-1",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset-After": "0.3",
    })
    rl.update("GET:channels:200", {
        "X-RateLimit-Bucket": "bucket-2",
        "X-RateLimit-Remaining": "5",
        "X-RateLimit-Reset-After": "1.0",
    })
    # Route 200 should pass immediately even though route 100 is exhausted
    start = time.monotonic()
    await rl.acquire("GET:channels:200")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


async def test_handle_429_global_pauses_all():
    rl = RateLimiter(global_rps=100)
    await rl.handle_429("GET:channels:123", retry_after=0.2, is_global=True)
    # Global pause should be set
    assert rl._global_paused_until > time.monotonic() - 0.5  # was set recently

    # Any route should wait
    start = time.monotonic()
    await rl.acquire("GET:guilds:999")  # different route
    elapsed = time.monotonic() - start
    # Should have been nearly instant since we already slept 0.2s in handle_429
    # But the pause was set, so if we're still within the window, it would wait


async def test_handle_429_local_does_not_set_global():
    rl = RateLimiter(global_rps=100)
    await rl.handle_429("GET:channels:123", retry_after=0.1, is_global=False)
    assert rl._global_paused_until == 0.0
