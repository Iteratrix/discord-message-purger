from discord_purger.parser.models import Reaction
from discord_purger.parser.package import parse_data_package

from .conftest import ChannelFixture, build_package


def test_end_to_end_json(tmp_path):
    pkg = build_package(
        tmp_path,
        user_id="user1",
        channels=[
            ChannelFixture("100", 0, "general", "g1", "Server A", ["1001", "1002", "1003"]),
            ChannelFixture("200", 1, "DM with Alice", None, None, ["2001"]),
            ChannelFixture("300", 3, "Group Chat", None, None, ["3001", "3002"]),
        ],
        activity_events=[
            {"event_type": "add_reaction", "channel_id": "100", "message_id": "9999", "emoji_name": "fire"},
        ],
    )

    result = parse_data_package(pkg)

    assert result.user_id == "user1"
    assert result.total_channels == 3
    assert result.total_messages == 6
    assert result.total_reactions == 1

    by_channel = result.messages_by_channel()
    assert set(by_channel.keys()) == {"100", "200", "300"}
    assert by_channel["100"] == ["1003", "1002", "1001"]  # sorted descending
    assert by_channel["200"] == ["2001"]

    assert Reaction("100", "9999", "fire") in result.reactions


def test_end_to_end_zip(tmp_path):
    pkg = build_package(
        tmp_path,
        user_id="user2",
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001", "5002"]),
        ],
        use_zip=True,
    )
    assert pkg.suffix == ".zip"

    result = parse_data_package(pkg)
    assert result.user_id == "user2"
    assert result.total_messages == 2


def test_csv_format(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["10", "20"]),
        ],
        message_format="csv",
    )

    result = parse_data_package(pkg)
    assert result.total_messages == 2
    assert result.channels[0].message_ids == ["20", "10"]  # sorted descending


def test_bare_channel_prefix(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001"]),
        ],
        use_c_prefix=False,
    )

    result = parse_data_package(pkg)
    assert result.total_messages == 1
    assert result.channels[0].channel_id == "111"


def test_lowercase_dirs(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001"]),
        ],
        uppercase_dirs=False,
    )

    result = parse_data_package(pkg)
    assert result.total_messages == 1


def test_empty_channel_excluded(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", []),  # empty
            ChannelFixture("222", 0, "dev", "g1", "Server", ["5001"]),
        ],
    )

    result = parse_data_package(pkg)
    assert result.total_channels == 1
    assert result.channels[0].channel_id == "222"


def test_thread_channels(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 11, "some-thread", "g1", "Server", ["5001", "5002"]),
            ChannelFixture("222", 12, "private-thread", "g1", "Server", ["5003"]),
        ],
    )

    result = parse_data_package(pkg)
    assert result.total_channels == 2
    assert result.total_messages == 3
    # Channels sorted by directory listing order; check both types present
    types = {ch.channel_type for ch in result.channels}
    assert types == {11, 12}


def test_no_activity_dir(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001"]),
        ],
        activity_events=None,
    )

    result = parse_data_package(pkg)
    assert result.total_reactions == 0
    assert any("not found" in w.message.lower() for w in result.warnings)


def test_large_channel(tmp_path):
    """10k messages should parse quickly."""
    ids = [str(i) for i in range(10000, 20000)]
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "busy", "g1", "Server", ids),
        ],
    )

    result = parse_data_package(pkg)
    assert result.total_messages == 10000
    # Verify sorted descending
    int_ids = [int(x) for x in result.channels[0].message_ids]
    assert int_ids == sorted(int_ids, reverse=True)


def test_channel_not_in_index(tmp_path):
    """Channel folder exists but not listed in index.json."""
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001"]),
        ],
    )
    # Overwrite index.json to not include channel 111
    import json
    index_file = list((tmp_path).glob("**/index.json"))[0]
    index_file.write_text(json.dumps({}))

    result = parse_data_package(pkg)
    assert result.total_channels == 1
    assert result.channels[0].channel_name == "Unknown"


def test_multiple_reactions_deduped(tmp_path):
    pkg = build_package(
        tmp_path,
        channels=[],
        activity_events=[
            {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "fire"},
            {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "fire"},
            {"event_type": "add_reaction", "channel_id": "c1", "message_id": "m1", "emoji_name": "heart"},
        ],
    )

    result = parse_data_package(pkg)
    assert result.total_reactions == 2


def test_warnings_accumulate(tmp_path):
    """Missing README, missing activity dir -- warnings should accumulate, not crash."""
    pkg = build_package(
        tmp_path,
        channels=[
            ChannelFixture("111", 0, "general", "g1", "Server", ["5001"]),
        ],
    )
    # Remove README.txt
    import os
    os.remove(tmp_path / "README.txt")

    result = parse_data_package(pkg)
    assert result.total_messages == 1
    assert any("README" in w.path for w in result.warnings)
