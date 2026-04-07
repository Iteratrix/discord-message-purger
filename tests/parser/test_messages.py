import json
from pathlib import Path

from discord_purger.parser.messages import (
    parse_channel_json,
    parse_channel_messages,
    parse_messages_csv,
    parse_messages_json,
)
from discord_purger.parser.resolve import PackageRoot


# --- parse_messages_json ---


def test_parse_json_standard():
    text = json.dumps([
        {"ID": "100", "Timestamp": "2024-01-01", "Contents": "hi", "Attachments": ""},
        {"ID": "200", "Timestamp": "2024-01-02", "Contents": "bye", "Attachments": ""},
    ])
    ids, warnings = parse_messages_json(text)
    assert ids == ["100", "200"]
    assert warnings == []


def test_parse_json_empty_array():
    ids, warnings = parse_messages_json("[]")
    assert ids == []
    assert warnings == []


def test_parse_json_malformed_entry():
    text = json.dumps([
        {"ID": "100"},
        {"no_id": "oops"},
        {"ID": "300"},
    ])
    ids, warnings = parse_messages_json(text)
    assert ids == ["100", "300"]
    assert len(warnings) == 1
    assert "missing ID" in warnings[0].message


def test_parse_json_invalid_json():
    ids, warnings = parse_messages_json("not json{{{")
    assert ids == []
    assert len(warnings) == 1
    assert "Invalid JSON" in warnings[0].message


def test_parse_json_not_array():
    ids, warnings = parse_messages_json('{"ID": "100"}')
    assert ids == []
    assert len(warnings) == 1
    assert "Expected JSON array" in warnings[0].message


# --- parse_messages_csv ---


def test_parse_csv_standard():
    text = "ID,Timestamp,Contents,Attachments\n100,2024-01-01,hello,\n200,2024-01-02,world,\n"
    ids, warnings = parse_messages_csv(text)
    assert ids == ["100", "200"]
    assert warnings == []


def test_parse_csv_empty():
    text = "ID,Timestamp,Contents,Attachments\n"
    ids, warnings = parse_messages_csv(text)
    assert ids == []
    assert warnings == []


def test_parse_csv_newlines_in_contents():
    # CSV with quoted fields containing newlines
    text = 'ID,Timestamp,Contents,Attachments\n100,2024-01-01,"line one\nline two\nline three",\n200,2024-01-02,normal,\n'
    ids, warnings = parse_messages_csv(text)
    assert ids == ["100", "200"]
    assert warnings == []


def test_parse_csv_missing_id():
    text = "ID,Timestamp,Contents,Attachments\n,2024-01-01,hello,\n200,2024-01-02,world,\n"
    ids, warnings = parse_messages_csv(text)
    assert ids == ["200"]
    assert len(warnings) == 1


# --- parse_channel_messages (integration with PackageRoot) ---


def _make_channel_dir(tmp_path: Path, channel_id: str, messages: list[dict] | None = None, use_csv: bool = False) -> Path:
    msgs = tmp_path / "Messages"
    msgs.mkdir(exist_ok=True)
    (msgs / "index.json").write_text(json.dumps({channel_id: "test"}))

    ch_dir = msgs / f"c{channel_id}"
    ch_dir.mkdir()
    (ch_dir / "channel.json").write_text(json.dumps({"id": channel_id, "type": 0}))

    if messages is not None:
        if use_csv:
            lines = ["ID,Timestamp,Contents,Attachments"]
            for m in messages:
                lines.append(f'{m["ID"]},{m.get("Timestamp", "")},{m.get("Contents", "")},{m.get("Attachments", "")}')
            (ch_dir / "messages.csv").write_text("\n".join(lines) + "\n")
        else:
            (ch_dir / "messages.json").write_text(json.dumps(messages))

    return tmp_path


def test_channel_messages_json_sorted_descending(tmp_path):
    pkg = _make_channel_dir(tmp_path, "111", [
        {"ID": "100"},
        {"ID": "300"},
        {"ID": "200"},
    ])
    with PackageRoot(pkg) as root:
        ids, warnings = parse_channel_messages(root, "c111")
        assert ids == ["300", "200", "100"]
        assert warnings == []


def test_channel_messages_csv_fallback(tmp_path):
    pkg = _make_channel_dir(tmp_path, "111", [
        {"ID": "50"},
        {"ID": "150"},
    ], use_csv=True)
    with PackageRoot(pkg) as root:
        ids, warnings = parse_channel_messages(root, "c111")
        assert ids == ["150", "50"]


def test_channel_messages_no_file(tmp_path):
    pkg = _make_channel_dir(tmp_path, "111", messages=None)
    with PackageRoot(pkg) as root:
        ids, warnings = parse_channel_messages(root, "c111")
        assert ids == []
        assert len(warnings) == 1
        assert "No messages.json or messages.csv" in warnings[0].message


def test_channel_messages_json_preferred_over_csv(tmp_path):
    """When both exist, JSON should be used."""
    pkg = _make_channel_dir(tmp_path, "111", [{"ID": "100"}])
    # Also write a CSV with different content
    ch_dir = tmp_path / "Messages" / "c111"
    (ch_dir / "messages.csv").write_text("ID,Timestamp,Contents,Attachments\n999,,,\n")
    with PackageRoot(pkg) as root:
        ids, _ = parse_channel_messages(root, "c111")
        assert ids == ["100"]  # from JSON, not CSV


# --- parse_channel_json ---


def test_channel_json_guild_channel(tmp_path):
    pkg = _make_channel_dir(tmp_path, "111", [])
    # Overwrite channel.json with guild info
    ch_dir = tmp_path / "Messages" / "c111"
    (ch_dir / "channel.json").write_text(json.dumps({
        "id": "111", "type": 0,
        "guild": {"id": "g1", "name": "My Server"},
    }))
    with PackageRoot(pkg) as root:
        ch_type, guild_id, guild_name, warnings = parse_channel_json(root, "c111")
        assert ch_type == 0
        assert guild_id == "g1"
        assert guild_name == "My Server"
        assert warnings == []


def test_channel_json_dm_channel(tmp_path):
    pkg = _make_channel_dir(tmp_path, "222", [])
    ch_dir = tmp_path / "Messages" / "c222"
    (ch_dir / "channel.json").write_text(json.dumps({
        "id": "222", "type": 1,
        "recipients": ["aaa", "bbb"],
    }))
    with PackageRoot(pkg) as root:
        ch_type, guild_id, guild_name, warnings = parse_channel_json(root, "c222")
        assert ch_type == 1
        assert guild_id is None
        assert guild_name is None


def test_channel_json_missing(tmp_path):
    msgs = tmp_path / "Messages"
    msgs.mkdir()
    ch_dir = msgs / "c333"
    ch_dir.mkdir()
    with PackageRoot(tmp_path) as root:
        ch_type, guild_id, guild_name, warnings = parse_channel_json(root, "c333")
        assert ch_type == 0  # default
        assert guild_id is None
        assert len(warnings) == 1
