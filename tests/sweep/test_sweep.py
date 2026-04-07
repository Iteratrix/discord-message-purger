from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from discord_purger.client.errors import ResourceUnavailable
from discord_purger.sweep.sweep import (
    DISCORD_EPOCH_MS,
    SweepResult,
    datetime_to_snowflake,
    search_sweep,
)


# --- datetime_to_snowflake ---


def test_snowflake_known_value():
    # 2024-01-01 00:00:00 UTC
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    unix_ms = int(dt.timestamp() * 1000)
    expected = str((unix_ms - DISCORD_EPOCH_MS) << 22)
    assert datetime_to_snowflake(dt) == expected


def test_snowflake_is_positive():
    dt = datetime(2020, 6, 15, tzinfo=timezone.utc)
    result = datetime_to_snowflake(dt)
    assert int(result) > 0


def test_snowflake_ordering():
    dt1 = datetime(2023, 1, 1, tzinfo=timezone.utc)
    dt2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert int(datetime_to_snowflake(dt1)) < int(datetime_to_snowflake(dt2))


# --- Helpers for mocking DiscordClient ---


async def _async_gen(items):
    """Create an async generator from a list."""
    for item in items:
        yield item


async def _async_gen_raise(items, exc):
    """Yield items then raise an exception (or raise immediately if items is empty)."""
    for item in items:
        yield item
    raise exc


def _make_client(
    guilds=None,
    dm_channels=None,
    guild_messages=None,
    channel_messages=None,
    guild_errors=None,
    channel_errors=None,
):
    """Build a mock DiscordClient with configurable search results.

    guild_messages: dict of guild_id -> list of message dicts
    channel_messages: dict of channel_id -> list of message dicts
    guild_errors: set of guild_ids that should raise ResourceUnavailable
    channel_errors: set of channel_ids that should raise ResourceUnavailable
    """
    client = MagicMock()
    client.get_guilds = AsyncMock(return_value=guilds or [])
    client.get_dm_channels = AsyncMock(return_value=dm_channels or [])

    guild_messages = guild_messages or {}
    channel_messages = channel_messages or {}
    guild_errors = guild_errors or set()
    channel_errors = channel_errors or set()

    def _guild_search(guild_id, author_id, *, min_id=None):
        if guild_id in guild_errors:
            return _async_gen_raise([], ResourceUnavailable(
                f"/guilds/{guild_id}/messages/search", 403, "Forbidden",
            ))
        return _async_gen(guild_messages.get(guild_id, []))

    def _channel_search(channel_id, author_id, *, min_id=None):
        if channel_id in channel_errors:
            return _async_gen_raise([], ResourceUnavailable(
                f"/channels/{channel_id}/messages/search", 403, "Forbidden",
            ))
        return _async_gen(channel_messages.get(channel_id, []))

    client.search_guild_messages = MagicMock(side_effect=_guild_search)
    client.search_channel_messages = MagicMock(side_effect=_channel_search)

    return client


# --- search_sweep tests ---


async def test_basic_sweep():
    client = _make_client(
        guilds=[{"id": "g1"}, {"id": "g2"}],
        dm_channels=[{"id": "dm1"}],
        guild_messages={
            "g1": [{"id": "m1", "channel_id": "c1"}, {"id": "m2", "channel_id": "c1"}],
            "g2": [{"id": "m3", "channel_id": "c2"}],
        },
        channel_messages={
            "dm1": [{"id": "m4", "channel_id": "dm1"}],
        },
    )

    result = await search_sweep(client, "user1")
    assert result.guilds_searched == 2
    assert result.dm_channels_searched == 1
    assert result.messages_found == 4
    assert result.messages_new == 4
    assert result.guilds_skipped == 0
    assert set(result.messages_by_channel.keys()) == {"c1", "c2", "dm1"}
    assert result.messages_by_channel["c1"] == ["m1", "m2"]


async def test_deduplication():
    client = _make_client(
        guilds=[{"id": "g1"}],
        guild_messages={
            "g1": [
                {"id": "known1", "channel_id": "c1"},
                {"id": "new1", "channel_id": "c1"},
                {"id": "known2", "channel_id": "c1"},
            ],
        },
    )

    result = await search_sweep(
        client, "user1",
        known_message_ids={"known1", "known2"},
    )
    assert result.messages_found == 3
    assert result.messages_new == 1
    assert result.messages_by_channel["c1"] == ["new1"]


async def test_standalone_mode():
    """No known IDs, no export timestamp — all messages returned."""
    client = _make_client(
        guilds=[{"id": "g1"}],
        guild_messages={
            "g1": [{"id": "m1", "channel_id": "c1"}, {"id": "m2", "channel_id": "c1"}],
        },
    )

    result = await search_sweep(client, "user1")
    assert result.messages_found == 2
    assert result.messages_new == 2


async def test_min_id_from_export_timestamp():
    """export_timestamp should be converted to min_id and passed to search."""
    client = _make_client(guilds=[{"id": "g1"}], guild_messages={"g1": []})

    ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
    await search_sweep(client, "user1", export_timestamp=ts)

    expected_min_id = datetime_to_snowflake(ts)
    client.search_guild_messages.assert_called_once_with(
        "g1", "user1", min_id=expected_min_id,
    )


async def test_no_min_id_when_no_timestamp():
    client = _make_client(guilds=[{"id": "g1"}], guild_messages={"g1": []})

    await search_sweep(client, "user1")

    client.search_guild_messages.assert_called_once_with(
        "g1", "user1", min_id=None,
    )


async def test_inaccessible_guild_skipped():
    client = _make_client(
        guilds=[{"id": "g1"}, {"id": "g2"}, {"id": "g3"}],
        guild_messages={
            "g1": [{"id": "m1", "channel_id": "c1"}],
            "g3": [{"id": "m2", "channel_id": "c3"}],
        },
        guild_errors={"g2"},
    )

    result = await search_sweep(client, "user1")
    assert result.guilds_searched == 2
    assert result.guilds_skipped == 1
    assert result.messages_new == 2


async def test_inaccessible_dm_skipped():
    client = _make_client(
        dm_channels=[{"id": "dm1"}, {"id": "dm2"}],
        channel_messages={"dm1": [{"id": "m1", "channel_id": "dm1"}]},
        channel_errors={"dm2"},
    )

    result = await search_sweep(client, "user1")
    assert result.dm_channels_searched == 1
    assert result.messages_new == 1


async def test_empty_results():
    client = _make_client(
        guilds=[{"id": "g1"}],
        guild_messages={"g1": []},
    )

    result = await search_sweep(client, "user1")
    assert result.guilds_searched == 1
    assert result.messages_found == 0
    assert result.messages_new == 0
    assert result.messages_by_channel == {}


async def test_messages_grouped_by_channel():
    """Messages from same channel across different guilds should be grouped."""
    client = _make_client(
        guilds=[{"id": "g1"}, {"id": "g2"}],
        guild_messages={
            # Both guilds have messages in the same channel
            # (unlikely in practice but tests the grouping logic)
            "g1": [{"id": "m1", "channel_id": "shared_channel"}],
            "g2": [{"id": "m2", "channel_id": "shared_channel"}],
        },
    )

    result = await search_sweep(client, "user1")
    assert result.messages_by_channel["shared_channel"] == ["m1", "m2"]


async def test_no_guilds_no_dms():
    client = _make_client(guilds=[], dm_channels=[])

    result = await search_sweep(client, "user1")
    assert result.guilds_searched == 0
    assert result.dm_channels_searched == 0
    assert result.messages_found == 0
    assert result.messages_by_channel == {}


async def test_total_channels_property():
    result = SweepResult(
        messages_by_channel={"c1": ["m1"], "c2": ["m2", "m3"]},
    )
    assert result.total_channels == 2
