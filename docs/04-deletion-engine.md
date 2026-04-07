# Module 4: Deletion Engine

## Purpose

Consume a manifest of message IDs and reaction events, then delete them as fast as Discord's rate limits allow using parallel async operations across channels. Provide progress reporting, resume capability, and a dry-run mode.

## Inputs

- `DiscordClient` instance (from Module 2)
- Message targets: list of `(channel_id, message_id)` pairs, grouped by channel
- Reaction targets: list of `(channel_id, message_id, emoji)` triples
- Configuration: concurrency, dry-run flag, resume state path

## Deletion Strategy

### Parallel Across Channels

Discord rate limits are **per-route** (effectively per-channel for deletion). We can delete in multiple channels simultaneously without them interfering with each other, up to the global 50 req/s ceiling.

- Use an asyncio semaphore to cap concurrent channel workers (default: 10)
- Each worker processes one channel at a time: iterate its message IDs and delete sequentially
- A global token bucket or semaphore enforces the ~45 req/s global ceiling

### Within a Channel

Delete messages one at a time, oldest first (or newest first — doesn't matter for correctness, but oldest-first means the channel "cleans up" visually from the bottom).

After each delete:
- Record the message ID as deleted in the resume state
- Sleep for the configured random delay (default 0.5-1.0s) on top of any rate limit waits

### Reaction Deletion

After messages are deleted (or concurrently), process reaction targets:
- `DELETE /channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me`
- These are on OTHER people's messages (your reactions on their messages), so the message still exists
- Emoji encoding: custom emoji → `name:id`, unicode → raw character, URL-encoded via `urllib.parse.quote()`
- Rate limit: ~4/second per channel (observed)

Reactions can be processed in parallel with message deletion since they target different messages.

## Resume State

A crash or interruption during a long purge (hours/days) should not require restarting from scratch.

### State File

Persist to a JSON file (default: `~/.config/discord-purger/state.json` or alongside the data package):

```json
{
  "started_at": "2026-03-19T12:00:00Z",
  "user_id": "123456789",
  "deleted_messages": {
    "channel_id_1": ["msg_id_1", "msg_id_2", ...],
    "channel_id_2": ["msg_id_3", ...]
  },
  "deleted_reactions": [
    {"channel_id": "...", "message_id": "...", "emoji": "..."}
  ],
  "failed_messages": {
    "channel_id_1": [{"message_id": "msg_id_4", "error": "403 Forbidden"}]
  },
  "completed_channels": ["channel_id_2"]
}
```

### Resume Behavior

On startup, if a state file exists:
- Load it and diff against the current manifest
- Skip any message/reaction already in `deleted_messages` / `deleted_reactions`
- Skip any channel in `completed_channels`
- Retry messages in `failed_messages` (they may now be deletable, or at least worth one more attempt)

### State Persistence

- Flush to disk periodically (every N deletions, or every M seconds) — not after every single delete (too much I/O)
- Also flush on clean shutdown (SIGINT/SIGTERM handler)
- Use atomic writes (write to temp file, then rename) to avoid corruption on crash

## Dry Run Mode

- Walk through the entire manifest and log what WOULD be deleted
- Do not make any API calls (except possibly `GET /users/@me` for validation)
- Output the same progress/stats as a real run
- Use a separate state file (`.dryrun.json`) to avoid corrupting real state

## Progress Reporting

Use `rich` for terminal output:

- **Overall progress bar**: X / total messages deleted
- **Per-channel status**: which channels are currently being processed, how many messages remain in each
- **Live stats**: deletion rate (messages/minute), estimated time remaining
- **Event log**: scrolling log of individual deletions, warnings, errors (below the progress display)
- **Summary on completion**: total deleted, total skipped (403/404), total failed, time elapsed

## Error Handling

| Error | Behavior |
|-------|----------|
| 403 Forbidden | Log warning, record in `failed_messages`, skip to next message |
| 404 Not Found | Message already deleted — log info, count as success, move on |
| 429 Rate Limited | Handled by API client (Module 2) — transparent retry |
| 5xx Server Error | Handled by API client — retry with backoff |
| 401 Unauthorized | Abort entire run — token is invalid/expired |
| Network error | Handled by API client — retry. If persistent, abort channel and move to next |
| `ReachedMaxRetries` | Record in `failed_messages`, skip to next message |

## Graceful Shutdown

On SIGINT (Ctrl+C):
- Stop starting new channel workers
- Let in-flight deletes complete (with a short timeout)
- Flush resume state
- Print summary of what was accomplished
- Exit cleanly

A second SIGINT should force-quit immediately.

## Interface Sketch

```python
@dataclass
class DeletionManifest:
    """What to delete, grouped for efficient parallel processing."""
    messages_by_channel: dict[str, list[str]]  # channel_id -> [message_ids]
    reactions: list[tuple[str, str, str]]       # (channel_id, message_id, emoji)

@dataclass
class DeletionResult:
    messages_deleted: int
    messages_skipped: int
    messages_failed: int
    reactions_deleted: int
    reactions_skipped: int
    elapsed: float

async def run_deletion(
    client: DiscordClient,
    manifest: DeletionManifest,
    *,
    dry_run: bool = False,
    state_path: Path | None = None,
    max_concurrency: int = 10,
) -> DeletionResult:
    ...
```

## Testing Strategy

- Mock API client to test parallel scheduling logic
- Test resume: create state file with partial progress, verify only remaining messages are attempted
- Test graceful shutdown: send SIGINT during a mock run, verify state is flushed
- Test dry run: verify no API calls are made
- Test error accumulation: inject 403s and 404s, verify correct counts and state recording
- Test progress display: verify rich output renders correctly (visual/manual test)
