from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from discord_purger.client import DiscordClient, ResourceUnavailable

DISCORD_EPOCH_MS = 1420070400000


def datetime_to_snowflake(dt: datetime) -> str:
    """Convert a datetime to a Discord snowflake ID.

    Useful as a min_id cutoff to limit search scope.
    """
    unix_ms = int(dt.timestamp() * 1000)
    return str((unix_ms - DISCORD_EPOCH_MS) << 22)


@dataclass(slots=True)
class SweepResult:
    messages_by_channel: dict[str, list[str]] = field(default_factory=dict)
    guilds_searched: int = 0
    dm_channels_searched: int = 0
    messages_found: int = 0
    messages_new: int = 0
    guilds_skipped: int = 0

    @property
    def total_channels(self) -> int:
        return len(self.messages_by_channel)


async def search_sweep(
    client: DiscordClient,
    user_id: str,
    *,
    known_message_ids: set[str] | None = None,
    export_timestamp: datetime | None = None,
    on_progress: Callable[[str, str, int], None] | None = None,
) -> SweepResult:
    """Search all accessible guilds and DM channels for the user's messages.

    Returns messages not already in known_message_ids, grouped by channel.
    Works as standalone discovery when known_message_ids and export_timestamp are None.

    on_progress(event, name, count) is called with:
      ("guild_start", guild_name, guild_index)
      ("guild_done", guild_name, messages_found_in_guild)
      ("guild_skipped", guild_name, 0)
      ("dm_start", channel_id, dm_index)
      ("dm_done", channel_id, messages_found_in_dm)
    """
    min_id = datetime_to_snowflake(export_timestamp) if export_timestamp else None

    messages: dict[str, list[str]] = defaultdict(list)
    found = 0
    new = 0
    guilds_searched = 0
    guilds_skipped = 0
    dm_channels_searched = 0

    def _progress(event: str, name: str, count: int) -> None:
        if on_progress:
            on_progress(event, name, count)

    # Search guilds
    guilds = await client.get_guilds()
    _progress("guilds_total", "", len(guilds))
    for i, guild in enumerate(guilds):
        guild_name = guild.get("name", guild["id"])
        _progress("guild_start", guild_name, i + 1)
        guild_found = 0
        try:
            async for msg in client.search_guild_messages(
                guild["id"], user_id, min_id=min_id,
            ):
                found += 1
                guild_found += 1
                message_id = msg["id"]
                if known_message_ids and message_id in known_message_ids:
                    continue
                messages[msg["channel_id"]].append(message_id)
                new += 1
            guilds_searched += 1
            _progress("guild_done", guild_name, guild_found)
        except ResourceUnavailable:
            guilds_skipped += 1
            _progress("guild_skipped", guild_name, 0)

    # Search DM channels
    dm_channels = await client.get_dm_channels()
    _progress("dms_total", "", len(dm_channels))
    for i, dm in enumerate(dm_channels):
        dm_id = dm["id"]
        _progress("dm_start", dm_id, i + 1)
        dm_found = 0
        try:
            async for msg in client.search_channel_messages(
                dm_id, user_id, min_id=min_id,
            ):
                found += 1
                dm_found += 1
                message_id = msg["id"]
                if known_message_ids and message_id in known_message_ids:
                    continue
                messages[msg["channel_id"]].append(message_id)
                new += 1
            dm_channels_searched += 1
            _progress("dm_done", dm_id, dm_found)
        except ResourceUnavailable:
            pass  # DM inaccessible, skip silently

    return SweepResult(
        messages_by_channel=dict(messages),
        guilds_searched=guilds_searched,
        dm_channels_searched=dm_channels_searched,
        messages_found=found,
        messages_new=new,
        guilds_skipped=guilds_skipped,
    )
