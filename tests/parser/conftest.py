from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class ChannelFixture:
    channel_id: str
    channel_type: int = 0
    channel_name: str = "test-channel"
    guild_id: str | None = "999888777666555444"
    guild_name: str | None = "Test Server"
    message_ids: list[str] = field(default_factory=list)


def build_package(
    tmp_path: Path,
    *,
    user_id: str = "123456789012345678",
    channels: list[ChannelFixture] | None = None,
    use_zip: bool = False,
    use_c_prefix: bool = True,
    uppercase_dirs: bool = True,
    message_format: Literal["json", "csv"] = "json",
    activity_events: list[dict] | None = None,
) -> Path:
    """Build a synthetic Discord data package for testing."""
    if channels is None:
        channels = []

    pkg_dir = tmp_path / "pkg" if use_zip else tmp_path

    # Account/user.json
    account_dir = pkg_dir / ("Account" if uppercase_dirs else "account")
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / "user.json").write_text(json.dumps({"id": user_id}))

    # Messages/index.json + channel dirs
    messages_dir = pkg_dir / ("Messages" if uppercase_dirs else "messages")
    messages_dir.mkdir(parents=True, exist_ok=True)

    index = {}
    for ch in channels:
        index[ch.channel_id] = ch.channel_name

        prefix = f"c{ch.channel_id}" if use_c_prefix else ch.channel_id
        ch_dir = messages_dir / prefix
        ch_dir.mkdir()

        # channel.json
        ch_data: dict = {"id": ch.channel_id, "type": ch.channel_type}
        if ch.guild_id:
            ch_data["guild"] = {"id": ch.guild_id, "name": ch.guild_name}
        if ch.channel_type in (1, 3):
            ch_data["recipients"] = [user_id, "other_user_id"]
        (ch_dir / "channel.json").write_text(json.dumps(ch_data))

        # messages file
        if message_format == "json":
            msgs = [{"ID": mid, "Timestamp": "2024-01-01", "Contents": "", "Attachments": ""} for mid in ch.message_ids]
            (ch_dir / "messages.json").write_text(json.dumps(msgs))
        else:
            lines = ["ID,Timestamp,Contents,Attachments"]
            for mid in ch.message_ids:
                lines.append(f"{mid},2024-01-01,,")
            (ch_dir / "messages.csv").write_text("\n".join(lines) + "\n")

    (messages_dir / "index.json").write_text(json.dumps(index))

    # README.txt
    (pkg_dir / "README.txt").write_text("Discord data package")

    # Activity logs
    if activity_events:
        analytics_dir = pkg_dir / "activity" / "analytics"
        analytics_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e) for e in activity_events]
        (analytics_dir / "events-2024-00001-of-00001.json").write_text("\n".join(lines) + "\n")

    if not use_zip:
        return pkg_dir

    # Zip it up
    zip_path = tmp_path / "package.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in pkg_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(pkg_dir))
    return zip_path
