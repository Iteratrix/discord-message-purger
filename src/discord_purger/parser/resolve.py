from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_CHANNEL_DIR_RE = re.compile(r"^c?(\d{2,22})$")


def resolve_channel_id(folder_name: str) -> str | None:
    m = _CHANNEL_DIR_RE.match(folder_name)
    return m.group(1) if m else None


class PackageRoot:
    """Uniform access to a Discord data package, whether zip or directory.

    Handles case-insensitive path resolution across all operations.
    Use as a context manager to ensure cleanup of temporary files.
    """

    def __init__(self, path: Path) -> None:
        self._tmp_dir: str | None = None

        if path.is_file() and zipfile.is_zipfile(path):
            self._tmp_dir = tempfile.mkdtemp(prefix="discord-purger-")
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(self._tmp_dir)
            self._root = Path(self._tmp_dir)
            # If the zip contains a single top-level directory, descend into it
            entries = list(self._root.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                self._root = entries[0]
        elif path.is_dir():
            self._root = path
        else:
            raise ValueError(f"Path is not a zip file or directory: {path}")

        # Build case-folded lookup for the root level
        self._case_map: dict[str, Path] = {}
        self._build_case_map(self._root, self._case_map)

    @staticmethod
    def _build_case_map(directory: Path, target: dict[str, Path]) -> None:
        for entry in directory.iterdir():
            target[entry.name.casefold()] = entry

    def _resolve_path(self, *parts: str) -> Path | None:
        current = self._root
        case_map = self._case_map

        for part in parts:
            resolved = case_map.get(part.casefold())
            if resolved is None:
                return None
            current = resolved
            if current.is_dir():
                case_map = {}
                self._build_case_map(current, case_map)

        return current

    def resolve(self, *parts: str) -> Path | None:
        return self._resolve_path(*parts)

    def iterdir(self, *parts: str) -> list[Path]:
        if not parts:
            return sorted(self._root.iterdir())
        resolved = self._resolve_path(*parts)
        if resolved is None or not resolved.is_dir():
            return []
        return sorted(resolved.iterdir())

    def read_text(self, *parts: str) -> str | None:
        resolved = self._resolve_path(*parts)
        if resolved is None or not resolved.is_file():
            return None
        return resolved.read_text(encoding="utf-8")

    def read_json(self, *parts: str) -> Any | None:
        text = self.read_text(*parts)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def close(self) -> None:
        if self._tmp_dir is not None:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    def __enter__(self) -> PackageRoot:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
