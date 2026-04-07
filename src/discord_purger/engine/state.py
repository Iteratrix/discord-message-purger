from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path


class DeletionState:
    """Tracks deletion progress with optional JSON persistence.

    When path is None, operates in-memory only (for dry runs and testing).
    Uses atomic writes (write temp, os.replace) to avoid corruption.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._deleted: dict[str, set[str]] = defaultdict(set)
        self._failed: dict[str, list[dict]] = defaultdict(list)
        self._deleted_reactions: set[tuple[str, str, str]] = set()
        self._completed_channels: set[str] = set()
        self._dirty = False

    # --- Tracking ---

    def mark_deleted(self, channel_id: str, message_id: str) -> None:
        self._deleted[channel_id].add(message_id)
        self._dirty = True

    def mark_failed(self, channel_id: str, message_id: str, error: str) -> None:
        self._failed[channel_id].append({"message_id": message_id, "error": error})
        self._dirty = True

    def mark_reaction_deleted(self, channel_id: str, message_id: str, emoji: str) -> None:
        self._deleted_reactions.add((channel_id, message_id, emoji))
        self._dirty = True

    def mark_channel_complete(self, channel_id: str) -> None:
        self._completed_channels.add(channel_id)
        self._dirty = True

    # --- Querying ---

    def is_deleted(self, channel_id: str, message_id: str) -> bool:
        return message_id in self._deleted.get(channel_id, set())

    def is_reaction_deleted(self, channel_id: str, message_id: str, emoji: str) -> bool:
        return (channel_id, message_id, emoji) in self._deleted_reactions

    def is_channel_complete(self, channel_id: str) -> bool:
        return channel_id in self._completed_channels

    # --- Stats ---

    @property
    def deleted_count(self) -> int:
        return sum(len(ids) for ids in self._deleted.values())

    @property
    def failed_count(self) -> int:
        return sum(len(entries) for entries in self._failed.values())

    # --- Persistence ---

    def flush(self) -> None:
        if self._path is None or not self._dirty:
            return

        data = {
            "deleted_messages": {
                ch: sorted(ids) for ch, ids in self._deleted.items()
            },
            "deleted_reactions": [
                {"channel_id": r[0], "message_id": r[1], "emoji": r[2]}
                for r in sorted(self._deleted_reactions)
            ],
            "failed_messages": dict(self._failed),
            "completed_channels": sorted(self._completed_channels),
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)
        self._dirty = False

    def load(self) -> None:
        if self._path is None or not self._path.exists():
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        for ch, ids in data.get("deleted_messages", {}).items():
            self._deleted[ch] = set(ids)

        for r in data.get("deleted_reactions", []):
            self._deleted_reactions.add((r["channel_id"], r["message_id"], r["emoji"]))

        for ch, entries in data.get("failed_messages", {}).items():
            self._failed[ch] = entries

        self._completed_channels = set(data.get("completed_channels", []))
        self._dirty = False
