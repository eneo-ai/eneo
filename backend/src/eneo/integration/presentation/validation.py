"""Shape constraints for identifiers that end up in Microsoft Graph URLs."""

from __future__ import annotations

from typing import Optional

# Graph site ids (host,guid,guid), drive ids (b!base64url), item and list ids
# are URL-safe tokens; anything else would have to be a path or query injection.
GRAPH_ID_PATTERN = r"^[A-Za-z0-9._,!=\-]*$"
GRAPH_ID_MAX_LENGTH = 512

# A display path of slash-separated segments; segments never contain slashes
# or control characters.
FOLDER_PATH_PATTERN = r"^(/[^/\x00-\x1f]+)*/?$"
FOLDER_PATH_MAX_LENGTH = 2048

SELECTED_ITEM_TYPES = ("file", "folder", "site_root")
RESOURCE_TYPES = ("site", "onedrive")


def validate_folder_path(value: Optional[str]) -> Optional[str]:
    """Reject paths with ``..`` segments; the pattern already rejects the rest."""
    if value is None:
        return None
    if any(segment in (".", "..") for segment in value.split("/")):
        raise ValueError("folder_path must not contain '.' or '..' segments")
    return value
