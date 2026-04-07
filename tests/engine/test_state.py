import json
from pathlib import Path

from discord_purger.engine.state import DeletionState


def test_mark_deleted_and_is_deleted():
    state = DeletionState()
    assert not state.is_deleted("c1", "m1")
    state.mark_deleted("c1", "m1")
    assert state.is_deleted("c1", "m1")
    assert not state.is_deleted("c1", "m2")
    assert not state.is_deleted("c2", "m1")


def test_mark_reaction_deleted():
    state = DeletionState()
    assert not state.is_reaction_deleted("c1", "m1", "fire")
    state.mark_reaction_deleted("c1", "m1", "fire")
    assert state.is_reaction_deleted("c1", "m1", "fire")
    assert not state.is_reaction_deleted("c1", "m1", "heart")


def test_mark_channel_complete():
    state = DeletionState()
    assert not state.is_channel_complete("c1")
    state.mark_channel_complete("c1")
    assert state.is_channel_complete("c1")
    assert not state.is_channel_complete("c2")


def test_deleted_count():
    state = DeletionState()
    state.mark_deleted("c1", "m1")
    state.mark_deleted("c1", "m2")
    state.mark_deleted("c2", "m3")
    assert state.deleted_count == 3


def test_failed_count():
    state = DeletionState()
    state.mark_failed("c1", "m1", "403")
    state.mark_failed("c1", "m2", "rate_limit")
    assert state.failed_count == 2


def test_flush_and_load(tmp_path):
    path = tmp_path / "state.json"
    state = DeletionState(path)
    state.mark_deleted("c1", "m1")
    state.mark_deleted("c1", "m2")
    state.mark_failed("c1", "m3", "403 Forbidden")
    state.mark_reaction_deleted("c2", "m4", "fire")
    state.mark_channel_complete("c1")
    state.flush()

    assert path.exists()

    # Load into a fresh state
    state2 = DeletionState(path)
    state2.load()
    assert state2.is_deleted("c1", "m1")
    assert state2.is_deleted("c1", "m2")
    assert not state2.is_deleted("c1", "m3")  # failed, not deleted
    assert state2.is_reaction_deleted("c2", "m4", "fire")
    assert state2.is_channel_complete("c1")
    assert state2.deleted_count == 2
    assert state2.failed_count == 1


def test_flush_creates_parent_dirs(tmp_path):
    path = tmp_path / "subdir" / "deep" / "state.json"
    state = DeletionState(path)
    state.mark_deleted("c1", "m1")
    state.flush()
    assert path.exists()


def test_flush_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "state.json"
    state = DeletionState(path)
    state.mark_deleted("c1", "m1")
    state.flush()
    # .tmp file should not remain
    assert not path.with_suffix(".tmp").exists()
    assert path.exists()


def test_no_op_when_path_is_none():
    state = DeletionState(None)
    state.mark_deleted("c1", "m1")
    state.flush()  # should not raise
    assert state.is_deleted("c1", "m1")


def test_dirty_tracking(tmp_path):
    path = tmp_path / "state.json"
    state = DeletionState(path)

    # Not dirty initially — flush is a no-op
    state.flush()
    assert not path.exists()

    # Mark something → dirty
    state.mark_deleted("c1", "m1")
    state.flush()
    assert path.exists()
    mtime1 = path.stat().st_mtime_ns

    # Flush again without changes → no-op (not dirty)
    state.flush()
    mtime2 = path.stat().st_mtime_ns
    assert mtime1 == mtime2


def test_load_nonexistent_path(tmp_path):
    path = tmp_path / "nonexistent.json"
    state = DeletionState(path)
    state.load()  # should not raise
    assert state.deleted_count == 0


def test_load_corrupted_json(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not valid json{{{")
    state = DeletionState(path)
    state.load()  # should not raise
    assert state.deleted_count == 0


def test_json_format(tmp_path):
    path = tmp_path / "state.json"
    state = DeletionState(path)
    state.mark_deleted("c1", "m2")
    state.mark_deleted("c1", "m1")
    state.mark_channel_complete("c1")
    state.flush()

    data = json.loads(path.read_text())
    assert data["deleted_messages"]["c1"] == ["m1", "m2"]  # sorted
    assert data["completed_channels"] == ["c1"]
