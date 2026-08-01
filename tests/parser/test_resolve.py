import json
import zipfile
from pathlib import Path

import pytest

from discord_purger.parser.resolve import PackageRoot, resolve_channel_id


# --- resolve_channel_id ---


def test_resolve_channel_id_with_c_prefix():
    assert resolve_channel_id("c100000000000000001") == "100000000000000001"


def test_resolve_channel_id_bare():
    assert resolve_channel_id("100000000000000001") == "100000000000000001"


def test_resolve_channel_id_not_a_channel():
    assert resolve_channel_id("not-a-channel") is None


def test_resolve_channel_id_too_short():
    assert resolve_channel_id("c1") is None


def test_resolve_channel_id_index_json():
    assert resolve_channel_id("index.json") is None


# --- PackageRoot from directory ---


def _make_dir_package(tmp_path: Path, *, uppercase: bool = True) -> Path:
    """Build a minimal data package directory."""
    account = tmp_path / ("Account" if uppercase else "account")
    account.mkdir()
    (account / "user.json").write_text(json.dumps({"id": "123"}))

    messages = tmp_path / ("Messages" if uppercase else "messages")
    messages.mkdir()
    (messages / "index.json").write_text(json.dumps({"111": "general"}))

    ch_dir = messages / "c111"
    ch_dir.mkdir()
    (ch_dir / "channel.json").write_text(json.dumps({"id": "111", "type": 0}))
    (ch_dir / "messages.json").write_text(json.dumps([{"ID": "m1"}]))

    (tmp_path / "README.txt").write_text("Discord data package")
    return tmp_path


def test_package_root_from_directory(tmp_path):
    pkg_dir = _make_dir_package(tmp_path)
    with PackageRoot(pkg_dir) as root:
        assert root.read_json("Account", "user.json") == {"id": "123"}


def test_package_root_case_insensitive(tmp_path):
    pkg_dir = _make_dir_package(tmp_path, uppercase=True)
    with PackageRoot(pkg_dir) as root:
        # Access with lowercase should still work
        assert root.read_json("account", "user.json") == {"id": "123"}
        assert root.read_json("messages", "index.json") == {"111": "general"}


def test_package_root_resolve_returns_none_for_missing(tmp_path):
    pkg_dir = _make_dir_package(tmp_path)
    with PackageRoot(pkg_dir) as root:
        assert root.resolve("nonexistent", "file.json") is None
        assert root.read_text("nonexistent") is None
        assert root.read_json("Account", "nonexistent.json") is None


def test_package_root_iterdir(tmp_path):
    pkg_dir = _make_dir_package(tmp_path)
    with PackageRoot(pkg_dir) as root:
        entries = root.iterdir("Messages")
        names = [e.name for e in entries]
        assert "c111" in names
        assert "index.json" in names


def test_package_root_iterdir_missing_dir(tmp_path):
    pkg_dir = _make_dir_package(tmp_path)
    with PackageRoot(pkg_dir) as root:
        assert root.iterdir("nonexistent") == []


def test_package_root_read_json_invalid(tmp_path):
    pkg_dir = _make_dir_package(tmp_path)
    (pkg_dir / "bad.json").write_text("not json{{{")
    with PackageRoot(pkg_dir) as root:
        assert root.read_json("bad.json") is None


# --- PackageRoot from zip ---


def _make_zip_package(tmp_path: Path) -> Path:
    """Build a data package directory then zip it."""
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    _make_dir_package(pkg_dir)

    zip_path = tmp_path / "package.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in pkg_dir.rglob("*"):
            zf.write(file, file.relative_to(pkg_dir))
    return zip_path


def test_package_root_from_zip(tmp_path):
    zip_path = _make_zip_package(tmp_path)
    with PackageRoot(zip_path) as root:
        assert root.read_json("Account", "user.json") == {"id": "123"}
        entries = root.iterdir("Messages")
        names = [e.name for e in entries]
        assert "c111" in names


def test_package_root_zip_cleanup(tmp_path):
    zip_path = _make_zip_package(tmp_path)
    root = PackageRoot(zip_path)
    tmp_dir = root._tmp_dir
    assert Path(tmp_dir).exists()
    root.close()
    assert not Path(tmp_dir).exists()


def test_package_root_context_manager_cleanup(tmp_path):
    zip_path = _make_zip_package(tmp_path)
    with PackageRoot(zip_path) as root:
        tmp_dir = root._tmp_dir
        assert Path(tmp_dir).exists()
    assert not Path(tmp_dir).exists()


# --- PackageRoot errors ---


def test_package_root_invalid_path(tmp_path):
    with pytest.raises(ValueError, match="not a zip file or directory"):
        PackageRoot(tmp_path / "nonexistent")


def test_package_root_regular_file_not_zip(tmp_path):
    f = tmp_path / "notazip.txt"
    f.write_text("hello")
    with pytest.raises(ValueError, match="not a zip file or directory"):
        PackageRoot(f)


# --- Lowercase directory names ---


def test_package_root_lowercase_dirs(tmp_path):
    pkg_dir = _make_dir_package(tmp_path, uppercase=False)
    with PackageRoot(pkg_dir) as root:
        # Access with uppercase should still work
        assert root.read_json("Account", "user.json") == {"id": "123"}
        assert root.read_json("Messages", "index.json") == {"111": "general"}
