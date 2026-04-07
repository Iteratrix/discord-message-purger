# Module 3: Search API Sweep

## Purpose

Supplementary discovery pass that finds messages NOT in the data package — specifically, messages sent after the export was generated. Uses Discord's search API to query by author across all guilds and DM channels, then produces a list of additional message IDs to delete.

This module is optional but important for completeness. The data package is a snapshot in time; the search sweep catches the gap between export and purge.

## When to Run

- **After** the data package has been parsed and its message IDs collected
- **Before** (or concurrent with) deletion — the sweep produces additional IDs for the deletion engine

## Discovery Strategy

### Guild Messages

For each guild the user is a member of:

```
GET /guilds/{guild_id}/messages/search?author_id={user_id}
```

This returns the user's messages across ALL channels in the guild (including threads, forums, announcement channels) in one query. No need to enumerate individual channels.

- Paginated: 25 messages per page, use `offset` parameter for pagination
- Returns messages newest-first
- Can filter by `min_id` to skip messages already known from the data package (use the newest message ID from the export as the cutoff)

### DM and Group DM Messages

DMs don't belong to a guild, so use the channel-level search:

```
GET /channels/{channel_id}/messages/search?author_id={user_id}
```

Need to enumerate DM channels first via `GET /users/@me/channels`, then search each one. Can use `min_id` to skip already-known messages.

### Optimization: min_id Cutoff

If the data package exists, we know the approximate export timestamp. Convert this to a snowflake ID and pass as `min_id` to the search API. This way the search only returns messages newer than the export — potentially just a handful instead of scanning the full history.

Discord snowflake formula: `snowflake = (unix_ms - 1420070400000) << 22`

If no data package is provided (user lost it, or running search-only mode), omit `min_id` and do a full sweep.

## Inputs

- `DiscordClient` instance (from Module 2)
- `user_id`: string
- `known_message_ids`: set of string snowflake IDs already discovered from the data package (for deduplication)
- `export_timestamp`: optional datetime — if provided, derive `min_id` to limit search scope

## Outputs

- List of `MessageTarget` objects not already in `known_message_ids`:
  - `channel_id`: string
  - `message_id`: string
- Updated channel list (any new channels discovered that weren't in the data package)

## Guild Discovery

The search sweep also serves as a guild/channel discovery mechanism:

- Call `GET /users/@me/guilds` (paginated, 200/page) to get all guilds
- Call `GET /users/@me/channels` to get all DM/group DM channels
- Compare against channels from the data package — log any new ones found

Note: `GET /users/@me/channels` only returns **recent/open** DM channels. Older closed DMs won't appear here but WILL be in the data package. This is another reason the data package is the primary source.

## Rate Limiting

The search endpoint is more aggressively rate-limited than other Discord endpoints. Observed limits:
- ~1 search request per 5-10 seconds per guild (much slower than message fetch/delete)
- This is fine — search is a one-time discovery pass, not a hot path

Respect rate limits via the API client (Module 2). No special handling needed here beyond what the client provides.

## Error Handling

- **403 on a guild search**: User may have been banned or the guild restricted search. Log warning, skip guild.
- **No results**: Normal — means no messages in that guild (or no new ones since export). Not an error.
- **Guild no longer accessible**: The user may have left or been kicked since the export. Skip gracefully.

## Standalone Mode

The search sweep should also work WITHOUT a data package, as a standalone discovery mechanism. In this mode:
- No `min_id` cutoff — search everything
- No deduplication set — all discovered messages are new
- This is the fallback for users who can't get or don't want to wait for a data package

## Interface Sketch

```python
@dataclass
class MessageTarget:
    channel_id: str
    message_id: str

async def search_sweep(
    client: DiscordClient,
    user_id: str,
    known_message_ids: set[str] | None = None,
    export_timestamp: datetime | None = None,
) -> list[MessageTarget]:
    """
    Search all accessible guilds and DM channels for the user's messages.
    Returns messages not already in known_message_ids.
    """
    ...
```

## Testing Strategy

- Mock search API responses with known message sets
- Test deduplication against a known_message_ids set
- Test min_id derivation from export timestamp
- Test standalone mode (no data package)
- Test guild pagination (200+ guilds)
- Test graceful handling of inaccessible guilds
