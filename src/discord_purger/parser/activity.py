from __future__ import annotations

import json

from .models import ParseWarning, Reaction
from .resolve import PackageRoot


_ACTIVITY_DIRS = ("analytics", "reporting")


def parse_activity_logs(root: PackageRoot) -> tuple[list[Reaction], list[ParseWarning]]:
    """Extract reaction events from activity log files.

    Searches activity/analytics/ and activity/reporting/ for add_reaction events.
    Deduplicates across files.
    """
    warnings: list[ParseWarning] = []
    seen: set[Reaction] = set()

    activity_entries = root.iterdir("activity")
    if not activity_entries:
        return [], [ParseWarning("activity/", "Activity directory not found")]

    for subdir_name in _ACTIVITY_DIRS:
        files = root.iterdir("activity", subdir_name)
        if not files:
            continue

        for file_path in files:
            if not file_path.is_file() or not file_path.name.endswith(".json"):
                continue

            rel_path = f"activity/{subdir_name}/{file_path.name}"
            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError as e:
                warnings.append(ParseWarning(rel_path, f"Could not read: {e}"))
                continue

            for line_num, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(ParseWarning(rel_path, f"Line {line_num}: invalid JSON"))
                    continue

                if not isinstance(event, dict):
                    continue
                if event.get("event_type") != "add_reaction":
                    continue

                channel_id = event.get("channel_id")
                message_id = event.get("message_id")
                emoji_name = event.get("emoji_name")

                if not all(isinstance(v, str) and v for v in (channel_id, message_id, emoji_name)):
                    warnings.append(ParseWarning(
                        rel_path,
                        f"Line {line_num}: add_reaction missing required fields",
                    ))
                    continue

                seen.add(Reaction(channel_id, message_id, emoji_name))

    return sorted(seen, key=lambda r: (r.channel_id, r.message_id, r.emoji_name)), warnings
