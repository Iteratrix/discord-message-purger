import pytest

from discord_purger.client.client import DiscordClient
from discord_purger.client.errors import AuthenticationError

from .conftest import MOCK_USER, discord_url, rate_limit_headers


@pytest.fixture
async def client():
    c = DiscordClient(
        "test-token",
        delete_delay=(0.0, 0.001),
        fetch_delay=(0.0, 0.001),
        retry_buffer=(0.01, 0.02),
        max_retries=2,
        global_rps=100,
    )
    await c._http.start()
    yield c
    await c._http.close()


# --- Context manager ---


async def test_context_manager(mock_api):
    mock_api.get(discord_url("/users/@me"), payload=MOCK_USER, headers=rate_limit_headers())
    async with DiscordClient("test-token", global_rps=100) as c:
        user = await c.get_current_user()
        assert user["id"] == MOCK_USER["id"]


# --- get_current_user ---


async def test_get_current_user(mock_api, client):
    mock_api.get(discord_url("/users/@me"), payload=MOCK_USER, headers=rate_limit_headers())
    user = await client.get_current_user()
    assert user["username"] == "testuser"


async def test_get_current_user_401(mock_api, client):
    mock_api.get(discord_url("/users/@me"), status=401, body="bad token", headers=rate_limit_headers())
    with pytest.raises(AuthenticationError):
        await client.get_current_user()


# --- get_guilds ---


async def test_get_guilds_single_page(mock_api, client):
    guilds = [{"id": str(i), "name": f"Guild {i}"} for i in range(50)]
    mock_api.get(
        discord_url("/users/@me/guilds?limit=200"),
        payload=guilds,
        headers=rate_limit_headers(),
    )
    result = await client.get_guilds()
    assert len(result) == 50


async def test_get_guilds_multi_page(mock_api, client):
    page1 = [{"id": str(i), "name": f"Guild {i}"} for i in range(200)]
    page2 = [{"id": str(i), "name": f"Guild {i}"} for i in range(200, 250)]

    mock_api.get(
        discord_url("/users/@me/guilds?limit=200"),
        payload=page1,
        headers=rate_limit_headers(),
    )
    mock_api.get(
        discord_url(f"/users/@me/guilds?limit=200&after=199"),
        payload=page2,
        headers=rate_limit_headers(),
    )
    result = await client.get_guilds()
    assert len(result) == 250


async def test_get_guilds_empty(mock_api, client):
    mock_api.get(
        discord_url("/users/@me/guilds?limit=200"),
        payload=[],
        headers=rate_limit_headers(),
    )
    result = await client.get_guilds()
    assert result == []


# --- get_guild_channels ---


async def test_get_guild_channels(mock_api, client):
    channels = [{"id": "c1", "type": 0, "name": "general"}]
    mock_api.get(
        discord_url("/guilds/g1/channels"),
        payload=channels,
        headers=rate_limit_headers(),
    )
    result = await client.get_guild_channels("g1")
    assert len(result) == 1
    assert result[0]["name"] == "general"


# --- get_dm_channels ---


async def test_get_dm_channels(mock_api, client):
    dms = [{"id": "dm1", "type": 1, "recipients": []}]
    mock_api.get(
        discord_url("/users/@me/channels"),
        payload=dms,
        headers=rate_limit_headers(),
    )
    result = await client.get_dm_channels()
    assert len(result) == 1


# --- search_guild_messages ---


def _search_response(messages: list[dict], total: int) -> dict:
    """Build a Discord search response. Each message wrapped in a context array."""
    return {
        "messages": [[msg] for msg in messages],
        "total_results": total,
    }


async def test_search_guild_single_page(mock_api, client):
    msgs = [{"id": "m1", "content": "hi"}, {"id": "m2", "content": "bye"}]
    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=0"),
        payload=_search_response(msgs, 2),
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_guild_messages("g1", "user1")]
    assert len(results) == 2
    assert results[0]["id"] == "m1"


async def test_search_guild_multi_page(mock_api, client):
    page1_msgs = [{"id": f"m{i}"} for i in range(25)]
    page2_msgs = [{"id": f"m{i}"} for i in range(25, 35)]

    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=0"),
        payload=_search_response(page1_msgs, 35),
        headers=rate_limit_headers(),
    )
    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=25"),
        payload=_search_response(page2_msgs, 35),
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_guild_messages("g1", "user1")]
    assert len(results) == 35


async def test_search_guild_empty(mock_api, client):
    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=0"),
        payload=_search_response([], 0),
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_guild_messages("g1", "user1")]
    assert results == []


async def test_search_guild_with_min_id(mock_api, client):
    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=0&min_id=999"),
        payload=_search_response([{"id": "m1000"}], 1),
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_guild_messages("g1", "user1", min_id="999")]
    assert len(results) == 1
    assert results[0]["id"] == "m1000"


async def test_search_yields_first_of_hit_group(mock_api, client):
    """Each hit group is [matched_msg, context1, context2...]. We yield only the first."""
    response = {
        "messages": [
            [{"id": "hit1", "hit": True}, {"id": "ctx1"}, {"id": "ctx2"}],
            [{"id": "hit2", "hit": True}, {"id": "ctx3"}],
        ],
        "total_results": 2,
    }
    mock_api.get(
        discord_url("/guilds/g1/messages/search?author_id=user1&offset=0"),
        payload=response,
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_guild_messages("g1", "user1")]
    assert len(results) == 2
    assert results[0]["id"] == "hit1"
    assert results[1]["id"] == "hit2"


# --- search_channel_messages ---


async def test_search_channel_paginates(mock_api, client):
    mock_api.get(
        discord_url("/channels/c1/messages/search?author_id=user1&offset=0"),
        payload=_search_response([{"id": "m1"}], 1),
        headers=rate_limit_headers(),
    )
    results = [msg async for msg in client.search_channel_messages("c1", "user1")]
    assert len(results) == 1


# --- delete_message ---


async def test_delete_message_success(mock_api, client):
    mock_api.delete(
        discord_url("/channels/c1/messages/m1"),
        status=204,
        headers=rate_limit_headers(),
    )
    assert await client.delete_message("c1", "m1") is True


async def test_delete_message_403(mock_api, client):
    mock_api.delete(
        discord_url("/channels/c1/messages/m1"),
        status=403,
        body="Forbidden",
        headers=rate_limit_headers(),
    )
    assert await client.delete_message("c1", "m1") is False


async def test_delete_message_404_is_success(mock_api, client):
    """404 means the message is already gone — that's a success."""
    mock_api.delete(
        discord_url("/channels/c1/messages/m1"),
        status=404,
        body="Not Found",
        headers=rate_limit_headers(),
    )
    assert await client.delete_message("c1", "m1") is True


# --- delete_reaction ---


async def test_delete_reaction_unicode(mock_api, client):
    # URL-encoded fire emoji
    mock_api.delete(
        discord_url("/channels/c1/messages/m1/reactions/%F0%9F%94%A5/@me"),
        status=204,
        headers=rate_limit_headers(),
    )
    assert await client.delete_reaction("c1", "m1", "\U0001f525") is True


async def test_delete_reaction_custom_emoji(mock_api, client):
    mock_api.delete(
        discord_url("/channels/c1/messages/m1/reactions/cool%3A123456/@me"),
        status=204,
        headers=rate_limit_headers(),
    )
    assert await client.delete_reaction("c1", "m1", "cool:123456") is True


async def test_delete_reaction_unavailable(mock_api, client):
    mock_api.delete(
        discord_url("/channels/c1/messages/m1/reactions/%F0%9F%94%A5/@me"),
        status=404,
        body="Not Found",
        headers=rate_limit_headers(),
    )
    assert await client.delete_reaction("c1", "m1", "\U0001f525") is False
