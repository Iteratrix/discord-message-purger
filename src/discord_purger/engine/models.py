from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeletionManifest:
    """What to delete, grouped for efficient parallel processing."""

    messages_by_channel: dict[str, list[str]] = field(default_factory=dict)
    reactions: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def total_messages(self) -> int:
        return sum(len(ids) for ids in self.messages_by_channel.values())

    @property
    def total_reactions(self) -> int:
        return len(self.reactions)


@dataclass(slots=True)
class DeletionResult:
    """Outcome of a deletion run."""

    messages_deleted: int = 0
    messages_skipped: int = 0
    messages_failed: int = 0
    reactions_deleted: int = 0
    reactions_skipped: int = 0
    elapsed: float = 0.0
