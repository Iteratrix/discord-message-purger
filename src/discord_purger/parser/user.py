from __future__ import annotations

from .models import ParseWarning
from .resolve import PackageRoot


def parse_user(root: PackageRoot) -> tuple[str, list[ParseWarning]]:
    """Extract the user ID from Account/user.json.

    Raises ValueError if the file is missing or has no 'id' field.
    """
    data = root.read_json("Account", "user.json")
    if data is None:
        raise ValueError(
            "Account/user.json not found in data package. "
            "This file is required to identify the account owner."
        )

    user_id = data.get("id")
    if not user_id or not isinstance(user_id, str):
        raise ValueError(
            "Account/user.json does not contain a valid 'id' field."
        )

    return user_id, []
