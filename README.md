# discord-purger

A fast, resumable CLI tool to bulk-delete all your Discord messages, reactions, and account data before deleting your account.

When you delete your Discord account, your messages **stay visible** - only your username is anonymized to "Deleted User." discord-purger reads your GDPR data export to build a complete deletion manifest, then deletes messages in parallel across channels as fast as rate limits allow.

> **Warning:** This tool uses your Discord user token to automate message deletion, which is against [Discord's Terms of Service](https://support.discord.com/hc/en-us/articles/115002192352). Use at your own risk. Your account could be suspended. Discord provides no official way to bulk-delete your own messages.

## How it works

1. **Parse your data package** — Discord's GDPR export contains every message ID you ever sent. The tool reads this to build a complete deletion manifest with zero API calls.
2. **Search sweep** — Catches messages sent after the export was generated using Discord's search API.
3. **Parallel deletion** — Deletes messages across multiple channels simultaneously, as fast as rate limits allow. Resumes automatically if interrupted.

### Advantages over existing tools

| | discord-purger | delete-me-discord | Undiscord |
|---|---|---|---|
| Discovery | Data package + search API | Full channel scan | Browser search |
| Threads/forums | Yes | No | Varies |
| Async parallel deletion | Yes | No (sequential) | No |
| Resume on crash | Yes | Partial | No |
| Reactions | Yes | Yes | No |
| Rate limiting | Proactive per-route tracking | Conservative fixed delays | Basic |

## Installation

Requires Python 3.12+.

```bash
# With uv (recommended)
uv tool install discord-purger

# With pip
pip install discord-purger

# From source
git clone https://github.com/youruser/discord-purger
cd discord-purger
uv sync
```

## Usage

### 1. Request your data package

Go to **Settings > Privacy & Safety > Request all of my Data** in Discord. This can take up to 30 days to arrive.

### 2. Get your Discord token

Open Discord in your browser, press F12 to open developer tools, go to the **Network** tab, and look for the `Authorization` header on any request to `discord.com/api`. Copy that value.

> **Never share your token.** It gives full access to your account.

### 3. Run the tool

```bash
# Dry run first to preview what will be deleted
discord-purger --package ~/Downloads/package.zip --token YOUR_TOKEN --dry-run -v

# Nuke it — delete messages, sweep for stragglers, clear profile,
# leave guilds, unfriend everyone. One command, walk away.
discord-purger --package ~/Downloads/package.zip --token YOUR_TOKEN --nuke
```

`--nuke` runs the full sequence: delete all messages and reactions from the data package, search sweep for post-export messages, verification sweep to catch anything missed, clear your profile, leave all guilds, and unfriend everyone. It resumes if interrupted.

For more control, you can run individual steps:

```bash
# Just delete messages (no profile/guild/friend changes)
discord-purger --package ~/Downloads/package.zip --token YOUR_TOKEN

# Search-only mode (no data package needed, slower)
discord-purger --search-only --token YOUR_TOKEN

# Just the profile/guild/friend purge
discord-purger --search-only --token YOUR_TOKEN --full-purge
```

### Options

```
--package PATH        Path to Discord data package (zip or directory)
--search-only         Run without a data package (uses search API only)
--token TOKEN         Discord user token (or set DISCORD_TOKEN env var)
--dry-run             Preview what would be deleted, no API calls
--state PATH          Resume state file (default: ~/.config/discord-purger/state.json)
--concurrency N       Max parallel channel workers (default: 10)
--no-sweep            Skip the supplementary search sweep
--no-reactions        Skip reaction deletion
--full-purge          Also clear profile, reset nicknames, leave guilds, unfriend everyone
-v, --verbose         Show detailed per-guild and per-channel progress
```

### Resuming an interrupted run

The tool saves progress to a state file after every 50 deletions and on shutdown (Ctrl+C). Just run the same command again — it picks up where it left off.

Press Ctrl+C once for a graceful shutdown (finishes in-flight deletes, saves state). Press Ctrl+C again to force quit.

## How long does it take?

Discord rate-limits deletions to roughly 1-5 per second per channel. With parallel channels (default 10), expect:

| Messages | Estimated time |
|----------|---------------|
| 1,000 | ~10-30 minutes |
| 10,000 | ~2-5 hours |
| 100,000 | ~1-2 days |

The tool shows a live progress bar with ETA.

## What else should I do before deleting my account?

With `--full-purge`, the tool handles: messages, reactions, profile (avatar/bio/banner/pronouns), server nicknames, leaving guilds, and unfriending everyone.

You still need to manually:

- Disconnect linked accounts (Settings > Connections)
- Deauthorize third-party apps (Settings > Authorized Apps)
- Remove payment methods and cancel Nitro
- Change email to a throwaway (Discord retains the last email for 180 days)
- Then delete your account

## Future features

- `--guild <id or name>` — target specific guilds
- `--channel <id>` — target specific channels
- `--before <date>` / `--after <date>` — filter by date range
- `--keep-last <N>` — preserve the last N messages per channel

## Development

```bash
git clone https://github.com/youruser/discord-purger
cd discord-purger
uv sync --dev
uv run pytest
```

## Troubleshooting

### Rate limit errors or slowdowns

Discord aggressively rate-limits message deletion - typically 3-5 requests per second per channel, with harsher limits on older messages in large guilds. The tool handles this automatically, but you may notice:

- **Long pauses (30-60s):** Discord returns `429 Too Many Requests` with a `Retry-After` header. The tool waits the required time and retries. This is normal.
- **Slower than expected:** Reduce `--concurrency` (try 3-5). More workers can trigger global rate limits that slow everything down.
- **"Rate limited" messages flooding the log:** This usually means Discord has applied a stricter limit to your account. Let the tool run - it backs off correctly - but expect longer completion times.

### Token expired or invalid

Discord tokens rotate periodically. If you get 401 errors, grab a fresh token from your browser (see step 2 above).

### Stuck on a specific message

Rarely, Discord refuses to delete a message (system messages, some webhook messages). The tool logs these and moves on. You can check the state file at `~/.config/discord-purger/state.json` for skipped message IDs.

## License

MIT
