# Technical Analysis: `delete-me-discord` v1.6.1

Reference analysis for building a faster Discord message purger. Every detail below is drawn directly from the installed source at `.venv/lib/python3.12/site-packages/delete_me_discord/`.

---

## 1. API Interaction Patterns

### Base URL and API Version

```python
BASE_URL = "https://discord.com/api/v10"
```

Uses Discord API **v10** throughout.

### Authentication

The token is obtained from (in order):
1. Constructor argument `token`
2. Environment variable `DISCORD_TOKEN`

The token is sent **raw** -- no `Bot ` or `Bearer ` prefix. This means it expects a **user token** (self-bot), not a bot token:

```python
self.headers = {
    "Authorization": self._token,       # raw user token, no prefix
    "Content-Type": "application/json"
}
self.session = requests.Session()
self.session.headers.update(self.headers)
```

A `requests.Session` is used for connection pooling. Headers are set once on the session.

### Resolving the Current User

```
GET /users/@me
```

Called in `__init__.py` at startup. The response is a single object (not a list), but `_request()` normalizes all responses into lists, so `get_current_user()` does `return self._request(url, ...)[0]`. The `id` field from the response is used throughout as `user_id`.

### Endpoints Used

| Purpose | Method | URL | Params |
|---------|--------|-----|--------|
| Current user | GET | `/users/@me` | none |
| List guilds | GET | `/users/@me/guilds` | none |
| Guild channels | GET | `/guilds/{guild_id}/channels` | none |
| DM channels | GET | `/users/@me/channels` | none |
| Fetch messages | GET | `/channels/{channel_id}/messages` | `limit=100`, `before={last_message_id}` |
| Fetch single msg | GET | `/channels/{channel_id}/messages` | `around={message_id}`, `limit=1` |
| Delete message | DELETE | `/channels/{channel_id}/messages/{message_id}` | none |
| Delete reaction | DELETE | `/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me` | none |

### How Pagination Works

**Cursor strategy:** Backward pagination using `before` parameter.

```python
params = {"limit": 100}
if last_message_id:
    params["before"] = last_message_id
```

- Batch size: **100** messages per request (Discord's maximum)
- After each batch, `last_message_id = response[-1]["id"]` (the oldest message in the batch)
- Stops when: response is empty, `max_messages` reached, or a message timestamp is older than `fetch_since`
- Messages arrive **newest-first** (descending by ID/time)

### Emoji Identifier Formatting

For reaction deletion, emojis are formatted as:
- Custom emoji: `{name}:{id}` (e.g., `emoji_name:123456789`)
- Unicode emoji: just `{name}` (e.g., the raw unicode character)

The identifier is URL-encoded via `urllib.parse.quote()` before being placed in the URL path.

---

## 2. Rate Limiting Strategy

### Sleep Durations (Defaults)

| Context | Default Range | CLI Flag |
|---------|--------------|----------|
| Between fetch batches | `[0.2, 0.4]` seconds | `--fetch-sleep-time` / `-f` |
| Between deletions | `[1.5, 2.0]` seconds | `--delete-sleep-time` / `-s` |
| Added after 429/5xx retry | `[25, 35]` seconds | `--retry-time-buffer` / `-b` |

All are randomized via `random.uniform(min, max)`. The user can provide 1 value (fixed) or 2 values (range).

### Retry Logic

```python
max_retries = 5  # default, configurable via --max-retries / -r
```

The core retry loop is in `_request()`:

```python
attempts = 0
while attempts <= self.max_retries:
    response = self.session.request(method=method, url=url, params=params)

    if response.status_code in {200, 204}:  # success
        ...
        return data
    elif response.status_code == 429 or 500 <= response.status_code < 600:  # retry
        retry_after = response.json().get("retry_after", 1)
        buffer = random.uniform(*self.retry_time_buffer)
        total_retry_after = retry_after + buffer
        time.sleep(total_retry_after)
        attempts += 1
    elif response.status_code == 401:
        raise AuthenticationError(...)
    elif response.status_code in {403, 404}:
        raise ResourceUnavailable(...)
    else:
        raise UnexpectedStatus(...)

raise ReachedMaxRetries(...)
```

Key points:
- **429 (rate limited):** Parses `retry_after` from the JSON body, adds the random buffer (default 25-35s), and sleeps. This is a very conservative buffer -- the actual Discord `retry_after` is usually 1-5 seconds.
- **5xx (server errors):** Treated exactly the same as 429 -- parsed for `retry_after` (defaults to 1 second if not present), plus the buffer.
- **Network errors** (`requests.RequestException`): Retries with `1 + random_buffer` seconds sleep.
- **401:** Raises `AuthenticationError`, which is caught at the top level to abort the run.
- **403/404:** Raises `ResourceUnavailable`, which callers typically catch and **skip** (log a warning, continue to next channel/message).
- **Other status codes:** Raises `UnexpectedStatus`, which propagates up and crashes.
- After `max_retries` exceeded: Raises `ReachedMaxRetries`, which propagates up and crashes.

### Rate Limit Scope

The tool has **no awareness of per-route or per-resource rate limits**. It applies a single global retry mechanism. Discord's rate limits are per-route (e.g., per-channel for message deletion), but this tool just sleeps and retries regardless. The very conservative sleep defaults (1.5-2s between deletes, 25-35s retry buffer) compensate for this lack of sophistication.

---

## 3. Message Discovery and Filtering

### Channel Enumeration

The discovery flow in `cleaner.get_all_channels()`:

1. **Fetch all guilds:** `GET /users/@me/guilds` -- returns all servers the user is in
2. **Fetch channels per guild:** `GET /guilds/{guild_id}/channels` -- called once per guild, sequentially
3. **Fetch DM channels:** `GET /users/@me/channels` -- returns recent DMs and group DMs

### Channel Type Filtering

Only three channel types are processed:

```python
channel_types = {0: "GuildText", 1: "DM", 3: "GroupDM"}
```

All other types are silently skipped with a debug log. **Not handled:**
- Type 2: Guild Voice
- Type 4: Guild Category (used for grouping only in discovery display, not processed)
- Type 5: Guild Announcement
- Type 10: Announcement Thread
- Type 11: Public Thread
- Type 12: Private Thread
- Type 13: Guild Stage Voice
- Type 14: Guild Directory
- Type 15: Guild Forum
- Type 16: Guild Media

### Include/Exclude Filtering

The `should_include_channel()` function in `utils.py` provides hierarchical filtering:

```python
# Priority order:
# 1. Explicit channel exclusion -> reject
# 2. Explicit channel inclusion -> accept
# 3. Parent/category inclusion -> accept (overrides guild exclusion)
# 4. Parent exclusion -> reject
# 5. Guild exclusion -> reject
# 6. If include_ids set, require match on channel/guild/parent -> reject if no match
# 7. Default -> accept
```

Filters work on channel IDs, guild IDs, and parent (category) IDs. This means you can exclude a whole guild but include a specific channel within it, or include a category to get all its channels.

### Message Fetching Within a Channel

All messages in a channel are fetched sequentially via backward pagination (see Section 1). The tool fetches **every message** in the channel, not just the user's own messages. Filtering happens client-side after fetch:

```python
is_author = message["author_id"] == self.user_id
is_deletable = is_author and message["type"].deletable
```

This is important: the tool downloads the entire channel history to find your messages. There is no server-side author filter.

### Message Type Enum -- Deletable vs Non-Deletable

From `type_enums.py`, the `MessageType` enum associates each type with a `deletable` boolean:

**Non-deletable types (False):**

| Value | Name | Why |
|-------|------|-----|
| 1 | RECIPIENT_ADD | System message, not user-authored |
| 2 | RECIPIENT_REMOVE | System message |
| 3 | CALL | System message |
| 4 | CHANNEL_NAME_CHANGE | System message |
| 5 | CHANNEL_ICON_CHANGE | System message |
| 21 | THREAD_STARTER_MESSAGE | Special reference message |
| 24 | AUTO_MODERATION_ACTION | Requires special permissions |

**Deletable types (True) -- 57 types including:**
- 0: DEFAULT (normal messages)
- 6: CHANNEL_PINNED_MESSAGE
- 7: USER_JOIN
- 8-11: GUILD_BOOST variants
- 18: THREAD_CREATED
- 19: REPLY
- 20: CHAT_INPUT_COMMAND (slash commands)
- 23: CONTEXT_MENU_COMMAND
- ...and many more system notification types

The enum cleverly uses `__new__` to store the boolean alongside the int value:

```python
def __new__(cls, value: int, deletable: bool):
    obj = int.__new__(cls, value)
    obj._value_ = value
    obj._deletable = deletable
    return obj
```

### DMs vs Servers -- Handling Differences

There is **no difference** in how DMs, group DMs, and server text channels are processed. They all go through the same `fetch_messages()` -> `delete_messages_older_than()` pipeline. The only difference is how they are discovered (root channels vs guild channels).

---

## 4. Deletion Logic

### The DELETE Endpoint

```
DELETE /channels/{channel_id}/messages/{message_id}
```

Expected success: HTTP 204 (no content).

### Failure Handling

- **403/404 (ResourceUnavailable):** Caught in `delete_message()`, logs a warning, returns `False`. The cleaner sees `False` and logs another warning but continues to the next message. **Does not retry.**
- **429/5xx:** Handled by the `_request()` retry loop (up to `max_retries` attempts).
- **401:** Raises `AuthenticationError`, which propagates up and kills the entire run.
- **`ReachedMaxRetries`:** Not caught by `delete_message()`, so it propagates up and crashes the run.

After a successful deletion, the tool sleeps `random.uniform(1.5, 2.0)` seconds (default) before the next delete.

### Reaction Deletion

```
DELETE /channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me
```

Only reactions where `reaction.get("me")` is True are deleted (i.e., only the authenticated user's own reactions).

Reactions are processed **only outside the preservation window** -- messages inside the preserve window have their reaction counts tracked but reactions are not removed.

The sleep after each reaction deletion uses the same `delete_sleep_time_range` as message deletion.

### Preservation Logic

Two preservation mechanisms work together:

#### 1. `--preserve-last` (time-based, default: 2 weeks)

```python
cutoff_time = datetime.now(timezone.utc) - self.preserve_last
```

Any message with `message_time >= cutoff_time` is preserved. Default is `timedelta(weeks=2)`.

#### 2. `--preserve-n` (count-based, default: 12)

Preserves the N most recent messages per channel. Two modes controlled by `--preserve-n-mode`:

- **`mine` (default):** Counts only the user's own deletable messages. Preserves the first 12 of those encountered (newest first).
- **`all`:** Counts all messages in the channel regardless of author. Preserves any of your deletable messages that fall within the first N messages.

```python
if preserve_count_active and (self.preserve_n_mode == "all" or is_deletable):
    preserve_n_count += 1

in_preserve_n_count_window = preserve_count_active and preserve_n_count <= self.preserve_n
in_preserve_window = in_preserve_n_count_window or message_time >= cutoff_time
```

A message is preserved if it's in **either** the time window **or** the count window.

#### Flow for each message:

1. Is the message within the preserve window (time or count)?
   - **Yes and deletable:** Log "preserving", increment `preserved_deletable_count`, add to `preserved_msg_ids`
   - **Yes and has user reactions:** Track reaction count as `preserved_reactions_count`
   - **No and deletable:** Delete it (or log "would delete" in dry run)
   - **No and has user reactions (and `--delete-reactions`):** Delete the reactions

### Preserve Cache

The preserve cache (`PreserveCache`) persists preserved message IDs between runs so that on the next run, those messages can be re-evaluated (they may now fall outside the preserve window):

- Stored at `~/.config/delete-me-discord/preserve_cache.json` by default
- JSON format: `{"schema_version": 1, "channels": {"channel_id": ["msg_id1", "msg_id2", ...]}}`
- IDs are stored in descending order (newest first)
- On load, cached IDs are merged with the live message stream via `_merge_cached_messages()`, which does a merge-sort-like interleave maintaining descending snowflake order
- Cached messages not found in the main fetch stream are individually fetched via `fetch_message_by_id()` using the `around` parameter
- In dry-run mode, the cache path is modified to `preserve_cache.dryrun.json` to avoid corrupting the real cache

---

## 5. Useful Patterns We Should Steal

### Error Recovery: Skip and Continue

The tool is designed for long-running jobs. Rather than aborting on a single inaccessible channel or message, it catches `ResourceUnavailable` at every call site and logs a warning:

```python
except ResourceUnavailable as e:
    self.logger.warning("Skipping channel %s (unavailable: %s).", channel_id, e)
    break  # or return False, depending on context
```

This is the right pattern. A user with hundreds of guilds will inevitably have channels they can't access.

### The `_request()` Normalization

All responses are normalized to `List[Dict]`:
- 204 -> `[]`
- Single object -> `[object]`
- List -> as-is

This simplifies all calling code. Worth replicating.

### Randomized Sleep Ranges

Every sleep duration is a `(min, max)` tuple randomized via `random.uniform()`. This is good practice to avoid detection patterns. The CLI accepts `--fetch-sleep-time MIN MAX` format.

### The Preserve Cache Merge

The `_merge_cached_messages()` generator is clever. It does an online merge of two descending-ordered streams (live API messages and cached IDs) without materializing either into a full list. Cached messages that fall "between" live messages are fetched individually via the `around` endpoint. This ensures previously-preserved messages get re-evaluated even if they've scrolled past the `fetch_max_age` window.

### Dry Run with Separate Cache

```python
if dry_run:
    base, ext = os.path.splitext(preserve_cache_path)
    preserve_cache_path = f"{base}.dryrun{ext or '.json'}"
```

Smart: dry runs don't corrupt the real preserve cache.

### JSON Output Mode

The tool supports `--json` which switches all logging to JSON lines and all discovery output to JSON. This makes it scriptable/parseable. The `JsonArgumentParser` subclass even emits parse errors as JSON.

### Message Data Extraction at Fetch Time

The tool extracts only what it needs from each message at fetch time, discarding the rest:

```python
yield {
    "message_id": message["id"],
    "timestamp": message["timestamp"],
    "channel_id": channel_id,
    "type": MessageType(message.get("type", 0)),
    "author_id": message.get("author", {}).get("id"),
    "reactions": message.get("reactions", []),
}
```

This keeps memory usage bounded. Worth replicating.

### Time Delta Parsing

The `parse_time_delta()` function supports both human-friendly formats:
- Legacy: `weeks=2,days=3,hours=5`
- Compact: `2w3d4h5m6s`

---

## 6. Limitations and Things We'd Do Differently

### 6.1. No Search API -- Full Channel Scan

**This is the biggest limitation.** The tool fetches ALL messages in a channel (`GET /channels/{channel_id}/messages` with pagination) and filters client-side by author. For a channel with 100k messages where you sent 50, this means fetching all 100k.

Discord has a **search endpoint** that we should use instead:

```
GET /channels/{channel_id}/messages/search?author_id={user_id}
GET /guilds/{guild_id}/messages/search?author_id={user_id}
```

The search endpoint supports server-side `author_id` filtering, date ranges (`min_id`, `max_id`), and returns only matching messages. This would be **orders of magnitude faster** for most use cases.

### 6.2. Sequential Processing

Everything is sequential:
- Guilds are fetched one at a time
- Channels are processed one at a time
- Messages are fetched then deleted one at a time

We should use **async I/O (aiohttp)** to:
- Fetch multiple channels concurrently
- Pipeline: start deleting messages while still fetching more
- Respect per-route rate limits properly with per-route semaphores

### 6.3. Missing Channel Types

Only types 0 (GuildText), 1 (DM), and 3 (GroupDM) are processed. Missing:
- **Type 5: Announcement channels** -- users can post in these
- **Type 10, 11, 12: Threads** (announcement, public, private) -- very common, messages live here
- **Type 13: Stage Voice** -- has a chat component
- **Type 15: Forum** -- each forum post is a thread
- **Type 16: Media** -- similar to forum

Threads are particularly important because many modern Discord servers route most conversation through threads.

### 6.4. Overly Conservative Rate Limiting

The default retry buffer of **25-35 seconds** on top of Discord's `retry_after` is extremely conservative. Discord typically says "retry after 1-5 seconds." Adding 25-35s on top means a single 429 costs 26-40 seconds. We should:
- Honor `retry_after` precisely with a small buffer (1-2s)
- Track rate limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) proactively
- Use per-route rate limit buckets

### 6.5. No Guild-Level Search

The tool doesn't use guild-wide search. Instead of iterating every channel in a guild, you can search across the entire guild at once:

```
GET /guilds/{guild_id}/messages/search?author_id={user_id}
```

This would eliminate the need to enumerate and iterate channels entirely for guild servers.

### 6.6. Synchronous HTTP with `requests`

Uses `requests.Session` (synchronous). For a tool that spends most of its time waiting on network I/O, switching to `aiohttp` or `httpx` async would allow concurrent operations without threads.

### 6.7. No Progress Persistence / Resumability

If the tool crashes mid-run, there's no way to resume where it left off. The preserve cache only tracks preserved messages, not "last processed channel" or "last deleted message." A crash after deleting 5000 of 10000 messages means re-scanning everything.

We should track deletion progress per channel (last processed message ID) so runs can be resumed.

### 6.8. No Bulk Delete

The tool deletes messages one at a time. Discord has a bulk delete endpoint:

```
POST /channels/{channel_id}/messages/bulk-delete
Body: {"messages": ["id1", "id2", ...]}  // 2-100 message IDs
```

However, this only works for messages **less than 14 days old** and requires the `MANAGE_MESSAGES` permission, so it's not usable for self-bot user tokens deleting your own messages in most cases. Still worth noting.

### 6.9. Guild Channel Fetch Has No Pagination

`GET /guilds/{guild_id}/channels` returns all channels at once (no pagination). For guilds with hundreds of channels this is fine (Discord returns them all), but the tool doesn't paginate `GET /users/@me/guilds` either -- it relies on Discord returning all guilds in one call. For users in 200+ guilds, this endpoint actually does paginate (returns 200 at a time), and the tool would miss guilds beyond the first page.

### 6.10. The `fetch_max_age` Optimization

The `--fetch-max-age` flag stops fetching messages older than a given time delta. This is a good optimization for recurring runs, but it's a poor substitute for the search API's date filtering which happens server-side. With `fetch_max_age`, the tool still fetches all messages from the API until it hits one older than the cutoff -- it just stops early rather than continuing to the end of history.

### 6.11. No Handling of "Message too old to delete"

Discord returns 403 or specific error codes when trying to delete very old messages (in some contexts). The tool catches 403 as `ResourceUnavailable` and skips, which is correct behavior, but it doesn't log the specific reason or track how many messages were skippable-but-not-deletable.

### 6.12. Dependencies

The tool uses only:
- `requests` (HTTP)
- `rich` (terminal output)

No async libraries, no specialized Discord libraries. This is actually nice for a simple tool, but we'd want `aiohttp` or `httpx[http2]` for performance.

---

## 7. Discord Data Package Format

Reference for parsing the GDPR data export (Settings > Privacy & Safety > Request all of my Data).

### Top-Level Structure

```
README.txt
Account/user.json
Account/avatar.png
Messages/index.json
Messages/c<channel_id>/          # one per channel you messaged in
  channel.json
  messages.json  (or messages.csv in pre-March 2024 exports)
Servers/index.json
Servers/<guild_id>/              # servers you own/admin
  guild.json, audit-log.json, channels.json, emoji.json, webhooks.json
activity/
  analytics/events-YYYY-NNNNN-of-NNNNN.json    # JSON-lines event logs
  modeling/events-YYYY-NNNNN-of-NNNNN.json
  reporting/events-YYYY-NNNNN-of-NNNNN.json
  tns/events-YYYY-NNNNN-of-NNNNN.json
```

**Casing varies** — `Account` vs `account`, `Messages` vs `messages`. Always check both.
**Channel folder prefix** — post-June 2021: `c<id>`, older: bare `<id>`. Detect with regex `/c?([0-9]{16,32})/`.

### Messages/index.json

Flat map of channel ID strings to human-readable names:

```json
{
  "464051583559139340": "general",
  "706821432894211234": "Direct Message with SomeUser",
  "893274612345678901": "Group DM Name"
}
```

### Messages/c<channel_id>/channel.json

```json
{
  "id": "464051583559139340",
  "type": 0,
  "name": "general",
  "guild": {"id": "123456789012345678", "name": "My Server"},
  "recipients": ["111111111111111111", "222222222222222222"]
}
```

| Field | Type | Present When |
|-------|------|-------------|
| `id` | string | Always |
| `type` | int (ChannelType) | Always |
| `name` | string or null | Server channels, named group DMs |
| `guild` | `{id, name}` | Server channels only |
| `recipients` | string array of user IDs | DMs and group DMs only |

**Channel types:**

| Value | Name |
|-------|------|
| 0 | GUILD_TEXT |
| 1 | DM |
| 2 | GUILD_VOICE |
| 3 | GROUP_DM |
| 5 | GUILD_ANNOUNCEMENT |
| 10 | ANNOUNCEMENT_THREAD |
| 11 | PUBLIC_THREAD |
| 12 | PRIVATE_THREAD |
| 13 | GUILD_STAGE_VOICE |
| 15 | GUILD_FORUM |
| 16 | GUILD_MEDIA |

### Messages/c<channel_id>/messages.json (post-March 2024)

Array of message objects. **Only YOUR sent messages** are included.

```json
[
  {
    "ID": "747951969171275807",
    "Timestamp": "2020-08-24 19:32:14.534000+00:00",
    "Contents": "Hello world",
    "Attachments": ""
  },
  {
    "ID": "747952108338094100",
    "Timestamp": "2020-08-24 19:32:47.752000+00:00",
    "Contents": "Check this out",
    "Attachments": "https://cdn.discordapp.com/attachments/.../image.png"
  }
]
```

| Field | Type | Notes |
|-------|------|-------|
| `ID` | string | Message snowflake ID |
| `Timestamp` | string | UTC datetime, variable precision (with/without microseconds) |
| `Contents` | string | May contain literal newlines |
| `Attachments` | string | Space-separated CDN URLs, or empty `""`. NOT a JSON array. |

### Messages/c<channel_id>/messages.csv (pre-March 2024)

```csv
ID,Timestamp,Contents,Attachments
747951969171275807,2020-08-24 19:32:14.534000+00:00,Hello world,
747952108338094100,2020-08-24 19:32:47.752000+00:00,Check this out,https://cdn.discordapp.com/...
```

Same four fields as the JSON format.

### Account/user.json

```json
{
  "id": "123456789012345678",
  "username": "myusername",
  "global_name": "My Display Name",
  "discriminator": "0",
  "relationships": [
    {"id": "...", "type": 1, "nickname": "...", "user": {"id": "...", "username": "..."}}
  ],
  "connections": [
    {"type": "steam", "name": "MyGamertag", "id": "..."}
  ],
  "payments": [...],
  "settings": {...}
}
```

**Relationship types:** 0=NONE, 1=FRIEND, 2=BLOCKED, 3=PENDING_INCOMING, 4=PENDING_OUTGOING, 5=IMPLICIT

### Reaction Data (activity/ event logs)

Reactions are NOT in the messages files. They're in `activity/analytics/` (or `activity/reporting/`) as JSON-lines (one JSON object per line):

```json
{"event_type": "add_reaction", "timestamp": "...", "guild_id": "...", "channel_id": "...", "message_id": "...", "emoji_name": "..."}
```

Other useful event types: `send_message`, `guild_joined`, `accepted_instant_invite`, `join_voice_channel`.

### Servers/index.json

Flat map of guild ID to guild name (all servers you're a member of, not just owned):

```json
{
  "123456789012345678": "My Cool Server",
  "234567890123456789": "Another Server"
}
```

### Key Parsing Caveats

1. **Only your messages** — no other authors' messages included
2. **Both CSV and JSON formats exist** — detect which is present
3. **Attachments are a space-separated string**, not a JSON array, even in JSON format
4. **Timestamps have variable precision** — may or may not include microseconds, may use `T` separator
5. **Contents can contain literal newlines** — handle when parsing CSV
6. **Case-insensitive folder names** — check both `Account` and `account`, etc.
7. **Format changed June 2025** — recent packages may have additional variations
