from __future__ import annotations

import csv
import io
import json

from .models import ParseWarning
from .resolve import PackageRoot


def parse_messages_json(text: str) -> tuple[list[str], list[ParseWarning]]:
    """Parse a messages.json file, returning message IDs."""
    warnings: list[ParseWarning] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [ParseWarning("messages.json", f"Invalid JSON: {e}")]

    if not isinstance(data, list):
        return [], [ParseWarning("messages.json", "Expected JSON array")]

    ids: list[str] = []
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            warnings.append(ParseWarning("messages.json", f"Entry {i}: not an object"))
            continue
        msg_id = obj.get("ID")
        if msg_id is None:
            warnings.append(ParseWarning("messages.json", f"Entry {i}: missing ID"))
            continue
        # ID can be string or int in different export versions
        ids.append(str(msg_id))

    return ids, warnings


def parse_messages_csv(text: str) -> tuple[list[str], list[ParseWarning]]:
    """Parse a messages.csv file, returning message IDs."""
    warnings: list[ParseWarning] = []
    ids: list[str] = []

    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader):
        msg_id = row.get("ID")
        if not msg_id or not msg_id.strip():
            warnings.append(ParseWarning("messages.csv", f"Row {i}: missing or empty ID"))
            continue
        ids.append(msg_id.strip())

    return ids, warnings


def parse_channel_messages(
    root: PackageRoot, channel_dir: str,
) -> tuple[list[str], list[ParseWarning]]:
    """Parse messages from a channel directory, trying JSON then CSV.

    Returns message IDs sorted descending (newest first).
    """
    # Try JSON first (newer format)
    text = root.read_text("Messages", channel_dir, "messages.json")
    if text is not None:
        ids, warnings = parse_messages_json(text)
    else:
        # Fall back to CSV
        text = root.read_text("Messages", channel_dir, "messages.csv")
        if text is not None:
            ids, warnings = parse_messages_csv(text)
        else:
            return [], [ParseWarning(
                f"Messages/{channel_dir}",
                "No messages.json or messages.csv found",
            )]

    # Sort descending by snowflake (integer value)
    ids.sort(key=lambda x: int(x), reverse=True)
    return ids, warnings


def parse_channel_json(
    root: PackageRoot, channel_dir: str,
) -> tuple[int, str | None, str | None, list[ParseWarning]]:
    """Parse channel.json for type, guild_id, guild_name."""
    data = root.read_json("Messages", channel_dir, "channel.json")
    if data is None:
        return 0, None, None, [ParseWarning(
            f"Messages/{channel_dir}/channel.json",
            "File missing or invalid, using defaults",
        )]

    raw_type = data.get("type", 0)
    channel_type = _normalize_channel_type(raw_type)
    guild = data.get("guild")
    guild_id = guild.get("id") if isinstance(guild, dict) else None
    guild_name = guild.get("name") if isinstance(guild, dict) else None

    return channel_type, guild_id, guild_name, []


_CHANNEL_TYPE_NAMES: dict[str, int] = {
    "GUILD_TEXT": 0,
    "DM": 1,
    "GUILD_VOICE": 2,
    "GROUP_DM": 3,
    "GUILD_CATEGORY": 4,
    "GUILD_ANNOUNCEMENT": 5,
    "ANNOUNCEMENT_THREAD": 10,
    "PUBLIC_THREAD": 11,
    "PRIVATE_THREAD": 12,
    "GUILD_STAGE_VOICE": 13,
    "GUILD_DIRECTORY": 14,
    "GUILD_FORUM": 15,
    "GUILD_MEDIA": 16,
}


def _normalize_channel_type(raw: int | str) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        return _CHANNEL_TYPE_NAMES.get(raw, 0)
    return 0
