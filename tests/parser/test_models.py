from discord_purger.parser.models import Channel, DataPackage, ParseWarning, Reaction


def test_channel_message_count():
    ch = Channel("1", 0, "general", "g1", "Server", ["a", "b", "c"])
    assert ch.message_count == 3


def test_channel_message_count_empty():
    ch = Channel("1", 0, "general", None, None, [])
    assert ch.message_count == 0


def test_reaction_is_hashable():
    r1 = Reaction("c1", "m1", "thumbsup")
    r2 = Reaction("c1", "m1", "thumbsup")
    assert r1 == r2
    assert len({r1, r2}) == 1


def test_reaction_different_emoji():
    r1 = Reaction("c1", "m1", "thumbsup")
    r2 = Reaction("c1", "m1", "heart")
    assert r1 != r2
    assert len({r1, r2}) == 2


def test_data_package_total_messages():
    pkg = DataPackage(
        user_id="123",
        channels=[
            Channel("1", 0, "a", None, None, ["m1", "m2"]),
            Channel("2", 0, "b", None, None, ["m3"]),
        ],
        reactions=[],
        warnings=[],
    )
    assert pkg.total_messages == 3


def test_data_package_totals_empty():
    pkg = DataPackage(user_id="123", channels=[], reactions=[], warnings=[])
    assert pkg.total_messages == 0
    assert pkg.total_channels == 0
    assert pkg.total_reactions == 0


def test_data_package_messages_by_channel():
    pkg = DataPackage(
        user_id="123",
        channels=[
            Channel("c1", 0, "a", None, None, ["m1", "m2"]),
            Channel("c2", 1, "b", None, None, ["m3"]),
        ],
        reactions=[],
        warnings=[],
    )
    assert pkg.messages_by_channel() == {"c1": ["m1", "m2"], "c2": ["m3"]}


def test_data_package_reaction_tuples():
    pkg = DataPackage(
        user_id="123",
        channels=[],
        reactions=[
            Reaction("c1", "m1", "thumbsup"),
            Reaction("c2", "m2", "heart"),
        ],
        warnings=[],
    )
    assert pkg.reaction_tuples() == [("c1", "m1", "thumbsup"), ("c2", "m2", "heart")]


def test_parse_warning_fields():
    w = ParseWarning("some/path", "something went wrong")
    assert w.path == "some/path"
    assert w.message == "something went wrong"
