# Module 1: Data Package Parser

## Purpose

Parse a Discord GDPR data export zip into a structured inventory of everything the user needs to delete: messages grouped by channel, reaction events, and account metadata. This is the primary discovery mechanism — it should produce a complete manifest that the deletion engine consumes.

## Inputs

- Path to a Discord data package (zip file or extracted directory)

## Outputs

A `DataPackage` object (or similar) containing:

- **user_id**: string — the authenticated user's snowflake ID (from `Account/user.json`)
- **channels**: list of `Channel` objects, each with:
  - `channel_id`: string
  - `channel_type`: int (0=GuildText, 1=DM, 3=GroupDM, 5=Announcement, 10-12=Threads, 15=Forum, etc.)
  - `channel_name`: string (from `Messages/index.json`)
  - `guild_id`: string or None
  - `guild_name`: string or None
  - `message_ids`: list of string snowflake IDs (sorted descending — newest first)
  - `message_count`: int
- **reactions**: list of `Reaction` objects, each with:
  - `channel_id`: string
  - `message_id`: string
  - `emoji_name`: string
- **summary stats**: total messages, total channels, total reactions, breakdown by channel type

## Format Handling

Must handle all known format variations:

- **Zip or directory**: accept either (extract zip to temp dir if needed)
- **Case-insensitive paths**: `Account/` vs `account/`, `Messages/` vs `messages/`
- **Channel folder prefix**: `c<id>` (post-June 2021) or bare `<id>` (older)
- **Message file format**: `messages.json` (post-March 2024) or `messages.csv` (older)
- **Timestamp precision**: with/without microseconds, `T` separator vs space
- **Contents with newlines**: must not break CSV parsing
- **Attachments field**: space-separated string, not a JSON array — we don't need to parse these for deletion, but could log attachment count for stats

## Activity Log Parsing (Reactions)

- Parse `activity/analytics/` and `activity/reporting/` directories
- Files are JSON-lines format (one JSON object per line)
- Extract events where `event_type == "add_reaction"`
- Pull `channel_id`, `message_id`, `emoji_name` from each
- Deduplicate (same reaction may appear in multiple activity files)

## Validation

- Verify required sentinel files exist: `README.txt`, `Account/user.json`, `Messages/index.json`
- Warn (don't fail) on channels where `channel.json` exists but message file is missing or empty
- Warn on unparseable message rows/objects (log and skip, don't abort)

## Edge Cases

- Empty channels (channel folder exists but messages file has 0 entries)
- Channels the user can no longer access (deleted servers, etc.) — still in the export, still need to attempt deletion
- Very large exports (users with 100k+ messages) — should stream/iterate, not load everything into memory at once
- Messages in channels not listed in `index.json` (shouldn't happen, but handle gracefully)

## Non-Goals

- Parsing message content (we only need IDs for deletion)
- Parsing attachment URLs (deleting the message removes attachments)
- Anything involving the Discord API (that's other modules)

## Interface Sketch

```python
@dataclass
class Channel:
    channel_id: str
    channel_type: int
    channel_name: str
    guild_id: str | None
    guild_name: str | None
    message_ids: list[str]

@dataclass
class Reaction:
    channel_id: str
    message_id: str
    emoji_name: str

@dataclass
class DataPackage:
    user_id: str
    channels: list[Channel]
    reactions: list[Reaction]

def parse_data_package(path: Path) -> DataPackage:
    """Parse a Discord data package zip or directory."""
    ...
```

## Testing Strategy

- Generate synthetic data packages covering all format variations
- Test: zip input, directory input, CSV format, JSON format, mixed case paths, c-prefix and bare prefix, empty channels, malformed rows, large channel with many messages, activity log reaction extraction
