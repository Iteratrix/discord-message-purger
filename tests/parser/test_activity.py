import json
from pathlib import Path

from discord_purger.parser.activity import parse_activity_logs
from discord_purger.parser.models import Reaction
from discord_purger.parser.resolve import PackageRoot


def _make_activity(tmp_path: Path, subdir: str, events: list[dict], filename: str = "events-2024-00001-of-00001.json") -> Path:
    activity_dir = tmp_path / "activity" / subdir
    activity_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in events]
    (activity_dir / filename).write_text("\n".join(lines) + "\n")
    return tmp_path


def test_parse_reactions_basic(tmp_path):
    _make_activity(tmp_path, "analytics", [
        {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "thumbsup"},
        {"event_type": "add_reaction", "channel_id": "c2", "message_id": "m2", "emoji_name": "heart"},
    ])
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert len(reactions) == 2
        assert Reaction("c1", "m1", "thumbsup") in reactions
        assert Reaction("c2", "m2", "heart") in reactions
        assert warnings == []


def test_ignores_other_event_types(tmp_path):
    _make_activity(tmp_path, "analytics", [
        {"event_type": "send_message", "channel_id": "c1", "message_id": "m1"},
        {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "ok"},
        {"event_type": "guild_joined", "guild_id": "g1"},
    ])
    with PackageRoot(tmp_path) as root:
        reactions, _ = parse_activity_logs(root)
        assert len(reactions) == 1
        assert reactions[0].emoji_name == "ok"


def test_dedup_across_files(tmp_path):
    event = {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "fire"}
    _make_activity(tmp_path, "analytics", [event])
    _make_activity(tmp_path, "reporting", [event])
    with PackageRoot(tmp_path) as root:
        reactions, _ = parse_activity_logs(root)
        assert len(reactions) == 1


def test_dedup_within_file(tmp_path):
    event = {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "fire"}
    _make_activity(tmp_path, "analytics", [event, event, event])
    with PackageRoot(tmp_path) as root:
        reactions, _ = parse_activity_logs(root)
        assert len(reactions) == 1


def test_malformed_json_line(tmp_path):
    activity_dir = tmp_path / "activity" / "analytics"
    activity_dir.mkdir(parents=True)
    (activity_dir / "events-2024-00001-of-00001.json").write_text(
        '{"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "ok"}\n'
        "not valid json\n"
        '{"event_type": "add_reaction", "channel_id": "c2", "message_id": "m2", "emoji_name": "yes"}\n'
    )
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert len(reactions) == 2
        assert any("invalid JSON" in w.message for w in warnings)


def test_missing_required_fields(tmp_path):
    _make_activity(tmp_path, "analytics", [
        {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1"},  # missing emoji_name
        {"event_type": "add_reaction", "channel_id": "c1", "emoji_name": "ok"},  # missing message_id
    ])
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert len(reactions) == 0
        assert len(warnings) == 2


def test_missing_activity_dir(tmp_path):
    # No activity/ directory at all
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert reactions == []
        assert len(warnings) == 1
        assert "not found" in warnings[0].message


def test_empty_activity_dir(tmp_path):
    (tmp_path / "activity").mkdir()
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert reactions == []
        # No warnings — empty is fine, just no data


def test_blank_lines_ignored(tmp_path):
    activity_dir = tmp_path / "activity" / "analytics"
    activity_dir.mkdir(parents=True)
    (activity_dir / "events-2024-00001-of-00001.json").write_text(
        "\n\n"
        '{"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "ok"}\n'
        "\n"
    )
    with PackageRoot(tmp_path) as root:
        reactions, warnings = parse_activity_logs(root)
        assert len(reactions) == 1
        assert warnings == []
