from __future__ import annotations

from pathlib import Path

from .activity import parse_activity_logs
from .messages import parse_channel_json, parse_channel_messages
from .models import Channel, DataPackage, ParseWarning
from .resolve import PackageRoot, resolve_channel_id
from .user import parse_user


def parse_data_package(path: Path, *, skip_reactions: bool = False) -> DataPackage:
    """Parse a Discord data package zip or directory into a deletion manifest."""
    with PackageRoot(path) as root:
        warnings: list[ParseWarning] = []

        # Validate sentinels
        if root.resolve("README.txt") is None:
            warnings.append(ParseWarning("README.txt", "Not found (may not be a Discord data package)"))

        # Parse user ID (fatal if missing)
        user_id, user_warnings = parse_user(root)
        warnings.extend(user_warnings)

        # Parse channel index
        index: dict[str, str] = root.read_json("Messages", "index.json") or {}
        if not index:
            warnings.append(ParseWarning("Messages/index.json", "Missing or empty"))

        # Iterate channel directories
        channels: list[Channel] = []
        messages_entries = root.iterdir("Messages")

        for entry in messages_entries:
            if not entry.is_dir():
                continue

            channel_id = resolve_channel_id(entry.name)
            if channel_id is None:
                continue

            channel_name = index.get(channel_id, "Unknown")

            ch_type, guild_id, guild_name, ch_warnings = parse_channel_json(root, entry.name)
            warnings.extend(ch_warnings)

            message_ids, msg_warnings = parse_channel_messages(root, entry.name)
            warnings.extend(msg_warnings)

            if not message_ids:
                continue

            channels.append(Channel(
                channel_id=channel_id,
                channel_type=ch_type,
                channel_name=channel_name,
                guild_id=guild_id,
                guild_name=guild_name,
                message_ids=message_ids,
            ))

        # Parse reactions from activity logs
        if skip_reactions:
            reactions = []
        else:
            reactions, activity_warnings = parse_activity_logs(root)
            warnings.extend(activity_warnings)

        return DataPackage(
            user_id=user_id,
            channels=channels,
            reactions=reactions,
            warnings=warnings,
        )
