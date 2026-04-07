from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Channel:
    channel_id: str
    channel_type: int
    channel_name: str
    guild_id: str | None
    guild_name: str | None
    message_ids: list[str]

    @property
    def message_count(self) -> int:
        return len(self.message_ids)


@dataclass(slots=True, frozen=True)
class Reaction:
    channel_id: str
    message_id: str
    emoji_name: str


@dataclass(slots=True)
class ParseWarning:
    path: str
    message: str


@dataclass(slots=True)
class DataPackage:
    user_id: str
    channels: list[Channel]
    reactions: list[Reaction]
    warnings: list[ParseWarning]

    @property
    def total_messages(self) -> int:
        return sum(ch.message_count for ch in self.channels)

    @property
    def total_channels(self) -> int:
        return len(self.channels)

    @property
    def total_reactions(self) -> int:
        return len(self.reactions)

    def messages_by_channel(self) -> dict[str, list[str]]:
        return {ch.channel_id: ch.message_ids for ch in self.channels}

    def reaction_tuples(self) -> list[tuple[str, str, str]]:
        return [(r.channel_id, r.message_id, r.emoji_name) for r in self.reactions]
