import json
from pathlib import Path

import pytest

from discord_purger.parser.resolve import PackageRoot
from discord_purger.parser.user import parse_user


def _make_package(tmp_path: Path, user_json: dict | None = None) -> Path:
    (tmp_path / "Account").mkdir()
    if user_json is not None:
        (tmp_path / "Account" / "user.json").write_text(json.dumps(user_json))
    return tmp_path


def test_parse_user_valid(tmp_path):
    pkg = _make_package(tmp_path, {"id": "123456789012345678", "username": "test"})
    with PackageRoot(pkg) as root:
        user_id, warnings = parse_user(root)
        assert user_id == "123456789012345678"
        assert warnings == []


def test_parse_user_extra_fields_ignored(tmp_path):
    pkg = _make_package(tmp_path, {
        "id": "999",
        "username": "x",
        "relationships": [],
        "payments": [],
    })
    with PackageRoot(pkg) as root:
        user_id, _ = parse_user(root)
        assert user_id == "999"


def test_parse_user_missing_file(tmp_path):
    pkg = _make_package(tmp_path, None)  # no user.json
    with PackageRoot(pkg) as root:
        with pytest.raises(ValueError, match="user.json not found"):
            parse_user(root)


def test_parse_user_missing_id_field(tmp_path):
    pkg = _make_package(tmp_path, {"username": "test"})
    with PackageRoot(pkg) as root:
        with pytest.raises(ValueError, match="valid 'id' field"):
            parse_user(root)


def test_parse_user_case_insensitive(tmp_path):
    # Lowercase 'account' directory
    (tmp_path / "account").mkdir()
    (tmp_path / "account" / "user.json").write_text(json.dumps({"id": "42"}))
    with PackageRoot(tmp_path) as root:
        user_id, _ = parse_user(root)
        assert user_id == "42"
