from __future__ import annotations

import asyncio
import signal
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from discord_purger.client import DiscordClient, RateLimitExceeded

from .models import DeletionManifest, DeletionResult
from .state import DeletionState

FLUSH_INTERVAL = 50  # flush state every N operations


async def run_deletion(
    client: DiscordClient,
    manifest: DeletionManifest,
    *,
    dry_run: bool = False,
    state_path: Path | None = None,
    max_concurrency: int = 10,
    on_progress: Callable[[str, str, str], None] | None = None,
) -> DeletionResult:
    """Delete messages and reactions from the manifest.

    Runs parallel workers across channels, respecting rate limits.
    Supports dry run, resume from state file, and graceful SIGINT shutdown.
    """
    state = DeletionState(state_path)
    state.load()

    result = DeletionResult()
    semaphore = asyncio.Semaphore(max_concurrency)
    shutdown = asyncio.Event()
    op_counter = _Counter()

    # SIGINT handling
    original_handler = signal.getsignal(signal.SIGINT)
    sigint_count = 0

    def _handle_sigint(sig: int, frame: object) -> None:
        nonlocal sigint_count
        sigint_count += 1
        if sigint_count == 1:
            shutdown.set()
        else:
            signal.signal(signal.SIGINT, original_handler)

    signal.signal(signal.SIGINT, _handle_sigint)

    start = time.monotonic()
    try:
        tasks: list[asyncio.Task] = []

        for channel_id, message_ids in manifest.messages_by_channel.items():
            if state.is_channel_complete(channel_id):
                continue
            tasks.append(asyncio.create_task(_delete_channel(
                client, channel_id, message_ids,
                state, result, semaphore, shutdown, dry_run, on_progress,
                op_counter,
            )))

        if manifest.reactions:
            tasks.append(asyncio.create_task(_delete_reactions(
                client, manifest.reactions,
                state, result, semaphore, shutdown, dry_run, on_progress,
                op_counter,
            )))

        if tasks:
            await asyncio.gather(*tasks)

    finally:
        result.elapsed = time.monotonic() - start
        state.flush()
        signal.signal(signal.SIGINT, original_handler)

    return result


class _Counter:
    """Simple mutable counter for tracking operations across tasks."""

    def __init__(self) -> None:
        self.value = 0

    def increment(self) -> int:
        self.value += 1
        return self.value


async def _delete_channel(
    client: DiscordClient,
    channel_id: str,
    message_ids: list[str],
    state: DeletionState,
    result: DeletionResult,
    semaphore: asyncio.Semaphore,
    shutdown: asyncio.Event,
    dry_run: bool,
    on_progress: Callable[[str, str, str], None] | None,
    op_counter: _Counter,
) -> None:
    async with semaphore:
        queue: deque[str] = deque(
            mid for mid in message_ids
            if not state.is_deleted(channel_id, mid)
        )

        if on_progress and queue:
            on_progress("channel_start", channel_id, str(len(queue)))

        while queue and not shutdown.is_set():
            msg_id = queue.popleft()

            if state.is_deleted(channel_id, msg_id):
                continue

            if dry_run:
                result.messages_deleted += 1
                if on_progress:
                    on_progress("deleted", channel_id, msg_id)
                continue

            try:
                success = await client.delete_message(channel_id, msg_id)
                if success:
                    state.mark_deleted(channel_id, msg_id)
                    result.messages_deleted += 1
                    if on_progress:
                        on_progress("deleted", channel_id, msg_id)
                else:
                    state.mark_failed(channel_id, msg_id, "unavailable")
                    result.messages_skipped += 1
                    if on_progress:
                        on_progress("skipped", channel_id, msg_id)
            except RateLimitExceeded:
                queue.append(msg_id)

            if op_counter.increment() % FLUSH_INTERVAL == 0:
                state.flush()

        if not shutdown.is_set():
            state.mark_channel_complete(channel_id)
            if on_progress:
                on_progress("channel_done", channel_id, "")


async def _delete_reactions(
    client: DiscordClient,
    reactions: list[tuple[str, str, str]],
    state: DeletionState,
    result: DeletionResult,
    semaphore: asyncio.Semaphore,
    shutdown: asyncio.Event,
    dry_run: bool,
    on_progress: Callable[[str, str, str], None] | None,
    op_counter: _Counter,
) -> None:
    async with semaphore:
        for channel_id, message_id, emoji in reactions:
            if shutdown.is_set():
                return

            if state.is_reaction_deleted(channel_id, message_id, emoji):
                continue

            if dry_run:
                result.reactions_deleted += 1
                if on_progress:
                    on_progress("reaction_deleted", channel_id, message_id)
                continue

            try:
                success = await client.delete_reaction(channel_id, message_id, emoji)
                if success:
                    state.mark_reaction_deleted(channel_id, message_id, emoji)
                    result.reactions_deleted += 1
                    if on_progress:
                        on_progress("reaction_deleted", channel_id, message_id)
                else:
                    result.reactions_skipped += 1
                    if on_progress:
                        on_progress("reaction_skipped", channel_id, message_id)
            except RateLimitExceeded:
                result.reactions_skipped += 1

            if op_counter.increment() % FLUSH_INTERVAL == 0:
                state.flush()
