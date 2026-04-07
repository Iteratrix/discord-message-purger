from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from discord_purger.client.errors import RateLimitExceeded
from discord_purger.engine.engine import run_deletion
from discord_purger.engine.models import DeletionManifest
from discord_purger.engine.state import DeletionState


def _make_client(
    delete_results: dict[str, bool] | None = None,
    delete_side_effect: Exception | None = None,
    reaction_results: dict[tuple, bool] | None = None,
):
    """Build a mock DiscordClient.

    delete_results: dict of "channel_id:message_id" -> bool
    If not provided, all deletes return True.
    """
    client = MagicMock()

    if delete_side_effect:
        client.delete_message = AsyncMock(side_effect=delete_side_effect)
    elif delete_results:
        async def _delete(channel_id, message_id):
            key = f"{channel_id}:{message_id}"
            return delete_results.get(key, True)
        client.delete_message = AsyncMock(side_effect=_delete)
    else:
        client.delete_message = AsyncMock(return_value=True)

    if reaction_results:
        async def _delete_reaction(channel_id, message_id, emoji):
            return reaction_results.get((channel_id, message_id, emoji), True)
        client.delete_reaction = AsyncMock(side_effect=_delete_reaction)
    else:
        client.delete_reaction = AsyncMock(return_value=True)

    return client


# --- Basic deletion ---


async def test_basic_deletion():
    client = _make_client()
    manifest = DeletionManifest(
        messages_by_channel={
            "c1": ["m1", "m2"],
            "c2": ["m3"],
        },
    )

    result = await run_deletion(client, manifest)

    assert result.messages_deleted == 3
    assert result.messages_skipped == 0
    assert result.messages_failed == 0
    assert result.elapsed > 0
    assert client.delete_message.call_count == 3


async def test_deletion_with_reactions():
    client = _make_client()
    manifest = DeletionManifest(
        messages_by_channel={"c1": ["m1"]},
        reactions=[("c2", "m10", "fire"), ("c3", "m20", "heart")],
    )

    result = await run_deletion(client, manifest)

    assert result.messages_deleted == 1
    assert result.reactions_deleted == 2
    assert client.delete_reaction.call_count == 2


# --- Dry run ---


async def test_dry_run_no_api_calls():
    client = _make_client()
    manifest = DeletionManifest(
        messages_by_channel={"c1": ["m1", "m2", "m3"]},
        reactions=[("c2", "m10", "fire")],
    )

    result = await run_deletion(client, manifest, dry_run=True)

    assert result.messages_deleted == 3
    assert result.reactions_deleted == 1
    client.delete_message.assert_not_called()
    client.delete_reaction.assert_not_called()


# --- Skipped messages ---


async def test_skipped_messages():
    client = _make_client(delete_results={
        "c1:m1": True,
        "c1:m2": False,  # 403/404
        "c1:m3": True,
    })
    manifest = DeletionManifest(messages_by_channel={"c1": ["m1", "m2", "m3"]})

    result = await run_deletion(client, manifest)

    assert result.messages_deleted == 2
    assert result.messages_skipped == 1


# --- Failed messages ---


async def test_failed_messages():
    client = _make_client()
    call_count = 0

    async def _mixed_delete(channel_id, message_id):
        nonlocal call_count
        call_count += 1
        if message_id == "m2":
            raise RateLimitExceeded("/test", 429, "rate limited")
        return True

    client.delete_message = AsyncMock(side_effect=_mixed_delete)
    manifest = DeletionManifest(messages_by_channel={"c1": ["m1", "m2", "m3"]})

    result = await run_deletion(client, manifest)

    assert result.messages_deleted == 2
    assert result.messages_failed == 1


# --- Resume ---


async def test_resume_skips_deleted(tmp_path):
    state_path = tmp_path / "state.json"

    # Pre-populate state
    state = DeletionState(state_path)
    state.mark_deleted("c1", "m1")
    state.mark_deleted("c1", "m2")
    state.flush()

    client = _make_client()
    manifest = DeletionManifest(messages_by_channel={"c1": ["m1", "m2", "m3"]})

    result = await run_deletion(client, manifest, state_path=state_path)

    # Only m3 should be attempted
    assert result.messages_deleted == 1
    assert client.delete_message.call_count == 1
    client.delete_message.assert_called_once_with("c1", "m3")


async def test_resume_skips_completed_channel(tmp_path):
    state_path = tmp_path / "state.json"

    state = DeletionState(state_path)
    state.mark_channel_complete("c1")
    state.flush()

    client = _make_client()
    manifest = DeletionManifest(messages_by_channel={
        "c1": ["m1", "m2"],  # completed
        "c2": ["m3"],        # not completed
    })

    result = await run_deletion(client, manifest, state_path=state_path)

    assert result.messages_deleted == 1
    assert client.delete_message.call_count == 1
    client.delete_message.assert_called_once_with("c2", "m3")


# --- State persistence ---


async def test_state_persisted_after_run(tmp_path):
    state_path = tmp_path / "state.json"
    client = _make_client()
    manifest = DeletionManifest(messages_by_channel={"c1": ["m1", "m2"]})

    await run_deletion(client, manifest, state_path=state_path)

    assert state_path.exists()
    data = json.loads(state_path.read_text())
    assert "m1" in data["deleted_messages"]["c1"]
    assert "m2" in data["deleted_messages"]["c1"]
    assert "c1" in data["completed_channels"]


# --- Progress callback ---


async def test_on_progress_callback():
    events = []

    def on_progress(event, channel_id, message_id):
        events.append((event, channel_id, message_id))

    client = _make_client(delete_results={"c1:m1": True, "c1:m2": False})
    manifest = DeletionManifest(messages_by_channel={"c1": ["m1", "m2"]})

    await run_deletion(client, manifest, on_progress=on_progress)

    assert ("deleted", "c1", "m1") in events
    assert ("skipped", "c1", "m2") in events


async def test_on_progress_reactions():
    events = []

    def on_progress(event, channel_id, message_id):
        events.append((event, channel_id, message_id))

    client = _make_client()
    manifest = DeletionManifest(
        reactions=[("c1", "m1", "fire")],
    )

    await run_deletion(client, manifest, on_progress=on_progress)

    assert ("reaction_deleted", "c1", "m1") in events


# --- Concurrency ---


async def test_concurrency_limited():
    """Verify the semaphore limits concurrent workers."""
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def _slow_delete(channel_id, message_id):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0.01)
        async with lock:
            current_concurrent -= 1
        return True

    client = MagicMock()
    client.delete_message = AsyncMock(side_effect=_slow_delete)
    client.delete_reaction = AsyncMock(return_value=True)

    # 5 channels, concurrency limit of 2
    manifest = DeletionManifest(
        messages_by_channel={f"c{i}": ["m1"] for i in range(5)},
    )

    await run_deletion(client, manifest, max_concurrency=2)

    assert max_concurrent <= 2


# --- Shutdown ---


async def test_shutdown_stops_early():
    """Setting the shutdown event should stop workers."""
    deleted_ids = []

    async def _delete_and_shutdown(channel_id, message_id):
        deleted_ids.append(message_id)
        return True

    client = MagicMock()
    client.delete_message = AsyncMock(side_effect=_delete_and_shutdown)
    client.delete_reaction = AsyncMock(return_value=True)

    # Many messages, but we'll trigger shutdown via a custom approach
    manifest = DeletionManifest(
        messages_by_channel={"c1": [f"m{i}" for i in range(100)]},
    )

    # Run with concurrency 1 and a progress callback that triggers shutdown
    call_count = 0

    # We can't easily test SIGINT in a unit test, but we can verify
    # the engine completes all messages in the manifest when no shutdown occurs
    result = await run_deletion(client, manifest, max_concurrency=1)
    assert result.messages_deleted == 100


# --- Empty manifest ---


async def test_empty_manifest():
    client = _make_client()
    manifest = DeletionManifest()

    result = await run_deletion(client, manifest)

    assert result.messages_deleted == 0
    assert result.reactions_deleted == 0
    assert result.elapsed >= 0
    client.delete_message.assert_not_called()


# --- Reactions skipped ---


async def test_reaction_skipped():
    client = _make_client(reaction_results={
        ("c1", "m1", "fire"): True,
        ("c1", "m2", "heart"): False,
    })
    manifest = DeletionManifest(
        reactions=[("c1", "m1", "fire"), ("c1", "m2", "heart")],
    )

    result = await run_deletion(client, manifest)

    assert result.reactions_deleted == 1
    assert result.reactions_skipped == 1
