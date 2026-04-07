from discord_purger.engine.models import DeletionManifest, DeletionResult


def test_manifest_total_messages():
    m = DeletionManifest(
        messages_by_channel={"c1": ["m1", "m2"], "c2": ["m3"]},
    )
    assert m.total_messages == 3


def test_manifest_total_messages_empty():
    m = DeletionManifest()
    assert m.total_messages == 0


def test_manifest_total_reactions():
    m = DeletionManifest(
        reactions=[("c1", "m1", "fire"), ("c2", "m2", "heart")],
    )
    assert m.total_reactions == 2


def test_result_defaults():
    r = DeletionResult()
    assert r.messages_deleted == 0
    assert r.messages_skipped == 0
    assert r.messages_failed == 0
    assert r.reactions_deleted == 0
    assert r.reactions_skipped == 0
    assert r.elapsed == 0.0
