from __future__ import annotations

import asyncio
import random
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

from .errors import ResourceUnavailable
from .http import HTTPClient


class DiscordClient:
    """High-level async client for the Discord REST API v10.

    Usage:
        async with DiscordClient(token) as client:
            user = await client.get_current_user()
            ...
    """

    def __init__(
        self,
        token: str,
        *,
        delete_delay: tuple[float, float] = (0.1, 0.3),
        fetch_delay: tuple[float, float] = (0.1, 0.3),
        retry_buffer: tuple[float, float] = (1.0, 3.0),
        max_retries: int = 5,
        global_rps: int = 45,
    ) -> None:
        self._http = HTTPClient(
            token,
            max_retries=max_retries,
            retry_buffer=retry_buffer,
            global_rps=global_rps,
        )
        self._delete_delay = delete_delay
        self._fetch_delay = fetch_delay

    async def __aenter__(self) -> DiscordClient:
        await self._http.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.close()

    # --- Discovery ---

    async def get_current_user(self) -> dict[str, Any]:
        _, data = await self._http.request("GET", "/users/@me")
        return data

    async def get_guilds(self) -> list[dict[str, Any]]:
        """List all guilds. Handles pagination (200/page)."""
        all_guilds: list[dict] = []
        after: str | None = None

        while True:
            params: dict[str, str] = {"limit": "200"}
            if after is not None:
                params["after"] = after

            _, page = await self._http.request(
                "GET", "/users/@me/guilds", params=params,
            )

            if not page:
                break

            all_guilds.extend(page)
            if len(page) < 200:
                break

            after = page[-1]["id"]
            await asyncio.sleep(random.uniform(*self._fetch_delay))

        return all_guilds

    async def get_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        _, data = await self._http.request("GET", f"/guilds/{guild_id}/channels")
        return data or []

    async def get_dm_channels(self) -> list[dict[str, Any]]:
        _, data = await self._http.request("GET", "/users/@me/channels")
        return data or []

    # --- Search ---

    async def search_guild_messages(
        self,
        guild_id: str,
        author_id: str,
        *,
        min_id: str | None = None,
        max_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for msg in self._search_messages(
            f"/guilds/{guild_id}/messages/search",
            author_id, min_id=min_id, max_id=max_id,
        ):
            yield msg

    async def search_channel_messages(
        self,
        channel_id: str,
        author_id: str,
        *,
        min_id: str | None = None,
        max_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for msg in self._search_messages(
            f"/channels/{channel_id}/messages/search",
            author_id, min_id=min_id, max_id=max_id,
        ):
            yield msg

    async def _search_messages(
        self,
        endpoint: str,
        author_id: str,
        *,
        min_id: str | None = None,
        max_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate through Discord search results.

        Response format: {"messages": [[hit, ctx...], [hit2, ctx...]], "total_results": N}
        First element of each inner array is the matched message.
        """
        offset = 0
        while True:
            params: dict[str, str] = {
                "author_id": author_id,
                "offset": str(offset),
            }
            if min_id is not None:
                params["min_id"] = min_id
            if max_id is not None:
                params["max_id"] = max_id

            _, data = await self._http.request("GET", endpoint, params=params)

            if data is None:
                break

            hits = data.get("messages", [])
            total = data.get("total_results", 0)

            if not hits:
                break

            for hit_group in hits:
                if hit_group:
                    yield hit_group[0]

            offset += len(hits)
            if offset >= total:
                break

            await asyncio.sleep(random.uniform(*self._fetch_delay))

    # --- Deletion ---

    async def delete_message(self, channel_id: str, message_id: str) -> bool:
        """Delete a message. Returns True on success or if already gone (404).
        Returns False if access denied (400/403)."""
        try:
            await self._http.request(
                "DELETE", f"/channels/{channel_id}/messages/{message_id}",
            )
            await asyncio.sleep(random.uniform(*self._delete_delay))
            return True
        except ResourceUnavailable as e:
            if e.status == 404:
                return True  # already deleted — that's a success
            return False

    async def delete_reaction(
        self, channel_id: str, message_id: str, emoji: str,
    ) -> bool:
        """Remove own reaction. Returns True on success, False if unavailable.

        emoji should be:
          - Unicode emoji: the raw character (e.g. "🔥")
          - Custom emoji: "name:id" format (e.g. "emoji_name:123456789")
        """
        encoded = urllib.parse.quote(emoji)
        try:
            await self._http.request(
                "DELETE",
                f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            )
            await asyncio.sleep(random.uniform(*self._delete_delay))
            return True
        except ResourceUnavailable:
            return False

    # --- Profile ---

    async def clear_profile(self) -> None:
        """Clear avatar, banner, bio, pronouns, and display name."""
        await self._http.request(
            "PATCH", "/users/@me",
            json_body={
                "avatar": None,
                "banner": None,
                "bio": "",
                "pronouns": "",
                "global_name": "",
            },
        )

    # --- Guilds ---

    async def reset_guild_nickname(self, guild_id: str) -> bool:
        """Reset nickname in a guild. Returns False if unavailable."""
        try:
            await self._http.request(
                "PATCH", f"/guilds/{guild_id}/members/@me",
                json_body={"nick": ""},
            )
            return True
        except ResourceUnavailable:
            return False

    async def leave_guild(self, guild_id: str) -> bool:
        """Leave a guild. Returns False if unavailable."""
        try:
            await self._http.request(
                "DELETE", f"/users/@me/guilds/{guild_id}",
            )
            return True
        except ResourceUnavailable:
            return False

    # --- Relationships ---

    async def get_relationships(self) -> list[dict[str, Any]]:
        """Get all relationships (friends, blocked, pending)."""
        _, data = await self._http.request("GET", "/users/@me/relationships")
        return data or []

    async def remove_relationship(self, user_id: str) -> bool:
        """Remove a relationship (unfriend/unblock). Returns False if unavailable."""
        try:
            await self._http.request(
                "DELETE", f"/users/@me/relationships/{user_id}",
            )
            return True
        except ResourceUnavailable:
            return False
