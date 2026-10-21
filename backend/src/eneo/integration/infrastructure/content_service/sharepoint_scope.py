"""SharePoint folder membership and current Graph location.

The sole owner of path normalization, ancestor checks and scope membership.
A failed location read is uncertainty, never evidence that content left scope.
No index writes, sync-state writes or orchestration belong here.

Graph percent-encodes ``parentReference.path`` and never an item's ``name``.
A Graph path is decoded exactly once, a name never: a folder named
"Budget 50%AB" must not lose "%AB" to a second decoding. Scope paths are
stored decoded.
"""

import unicodedata
from typing import Optional, cast
from urllib.parse import unquote

import aiohttp

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.parsing import has_graph_facet
from eneo.integration.infrastructure.content_service.types import SharePointItem
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

logger = get_logger(__name__)


class ScopeFolderUnavailable(Exception):
    """Graph could not tell us where the selected folder is right now.

    Raised before any item of a delta pass is classified: the stored path may
    be stale (an ancestor renamed or moved), and classifying against it would
    delete every nested file as out of scope. The pass fails with its token
    kept and is replayed by the next sync.
    """

    def __init__(self, cause: Exception) -> None:
        super().__init__(
            f"Could not read the selected folder from SharePoint: "
            f"{user_visible_error(cause)}"
        )


def is_ancestor_of_scope(
    item: SharePointItem, scope_folder_path: Optional[str]
) -> bool:
    """Whether the folder entry's own path lies above the scope folder's.

    The scope folder itself is not an ancestor: its own entry (a rename or
    move) is in scope and counted like any other folder.
    """
    if not scope_folder_path:
        return False
    own_path = folder_path_from_item(item)
    if not own_path:
        return False
    own = normalize_path(own_path)
    return bool(own) and any(
        scope.startswith(own + "/") for scope in _scope_forms(scope_folder_path)
    )


async def current_scope_folder_path(
    content_client: SharePointContentClient,
    drive_id: str,
    scope_folder_id: str,
) -> Optional[str]:
    """The scope folder's path as Graph has it now; ``None`` when the folder is gone.

    Only a 404 is an answer about the folder; any other failure says nothing
    about where it is, so it fails the pass instead of letting the stored
    path, which may be stale, decide what is out of scope.
    """
    try:
        folder_metadata = await content_client.get_file_metadata(
            drive_id=drive_id, item_id=scope_folder_id
        )
    except aiohttp.ClientResponseError as exc:
        if exc.status != 404:
            raise ScopeFolderUnavailable(exc) from exc
        logger.warning(
            "Scope folder %s is gone (404); classifying against the stored path",
            scope_folder_id,
        )
        return None
    except Exception as exc:
        raise ScopeFolderUnavailable(exc) from exc
    return folder_path_from_item(cast(SharePointItem, folder_metadata))


def scope_folder_path_from_changes(
    changes: list[SharePointItem], scope_folder_id: str
) -> Optional[str]:
    for item in changes:
        if item.get("id") != scope_folder_id or has_graph_facet(item, "deleted"):
            continue
        return folder_path_from_item(item)
    return None


def is_item_in_folder_scope(
    item: SharePointItem,
    scope_folder_id: Optional[str],
    scope_folder_path: Optional[str] = None,
    known_subfolder_ids: Optional[set[str]] = None,
    selected_item_type: Optional[str] = None,
) -> bool:
    """
    Check if an item is within the scope of a selected folder/file.

    Behavior depends on selected_item_type:
    - "file": Only include the specific file (item.id == scope_folder_id)
    - "folder": Include direct children and all descendants of the folder
    - "site_root" or None: Include all items (no filtering)

    For folder scope, an item is in scope if:
    - It is the selected folder itself, OR
    - Its parent is the scope folder itself, OR
    - Its parentReference.path contains the scope folder path (nested descendant)
    """
    if not scope_folder_id:
        return True

    item_id = item.get("id")

    # If selected_item_type is "file", only include the exact file
    if selected_item_type == "file":
        return item_id == scope_folder_id

    # If selected_item_type is "site_root", include everything
    if selected_item_type == "site_root" or selected_item_type is None:
        return True

    # For "folder" type, check if item is in the folder hierarchy
    if selected_item_type == "folder" and item_id == scope_folder_id:
        return True

    parent_ref = item.get("parentReference", {})
    parent_id = parent_ref.get("id")

    # Direct child of the scope folder
    if parent_id == scope_folder_id:
        return True

    # Child of an in-scope folder of the same change set.
    if known_subfolder_ids and parent_id in known_subfolder_ids:
        return True

    # Check nested descendants via parentReference.path
    # Graph API returns paths like "/drives/{id}/root:/Documents/Reports"
    # We match against the stored folder_path (e.g. "/Documents/Reports")
    if scope_folder_path:
        relative_path = extract_relative_graph_path(parent_ref.get("path", ""))

        # Item is in scope if its parent path starts with or equals the folder
        # path. SharePoint paths are case-insensitive and Graph's arrive
        # percent-encoded (e.g. "%20", encoded å/ä/ö), so normalize both sides
        # before comparing — otherwise folders with spaces or non-ASCII names
        # silently fail the scope check and never get indexed.
        normalized_parent = normalize_path(unquote(relative_path))
        for normalized_scope in _scope_forms(scope_folder_path):
            if normalized_scope and (
                normalized_parent == normalized_scope
                or normalized_parent.startswith(normalized_scope + "/")
            ):
                return True

    return False


def parent_path(item: SharePointItem) -> Optional[str]:
    return item.get("parentReference", {}).get("path") or None


def folder_path_from_item(item: SharePointItem) -> Optional[str]:
    """The folder's decoded drive-relative path: its parent's path plus its name."""
    relative_parent_path = unquote(
        extract_relative_graph_path(item.get("parentReference", {}).get("path", ""))
    )
    folder_name = str(item.get("name", "")).strip("/")

    if relative_parent_path == "/":
        return f"/{folder_name}" if folder_name else "/"
    if relative_parent_path:
        return (
            f"{relative_parent_path.rstrip('/')}/{folder_name}"
            if folder_name
            else relative_parent_path
        )
    return None


def normalize_path(path: str) -> str:
    """Normalize a decoded SharePoint path for case-insensitive comparison.

    Normalizes Unicode to NFC (so å/ä/ö in NFC vs NFD forms compare equal),
    strips a trailing slash, and casefolds. Decoding is the caller's: a path
    is decoded once, where it comes from Graph.
    """
    if not path:
        return ""
    nfc = unicodedata.normalize("NFC", path)
    return nfc.rstrip("/").casefold()


def _scope_forms(scope_folder_path: str) -> set[str]:
    """The stored scope path, and decoded once more for a path stored before
    scope paths were stored decoded; a pass refreshes it before it decides."""
    return {
        normalize_path(scope_folder_path),
        normalize_path(unquote(scope_folder_path)),
    }


def extract_relative_graph_path(parent_path: str) -> str:
    """Convert Graph parentReference.path to a comparable relative path."""
    if not parent_path:
        return ""
    if ":/" in parent_path:
        return parent_path.split(":", 1)[1]
    if "root:" in parent_path:
        return "/"
    return parent_path


async def enumerate_items(
    *,
    client: SharePointContentClient,
    resource_type: str,
    site_id: Optional[str],
    drive_id: str,
    folder_id: Optional[str],
) -> list[SharePointItem]:
    """Strictly enumerate every in-scope file (and page) item.

    Listing errors propagate instead of being swallowed: an incomplete
    enumeration must NOT be treated as the authoritative set during
    reconciliation, or it would delete valid blobs.
    """
    items: list[SharePointItem] = []

    async def _walk(current_folder_id: Optional[str]) -> None:
        if resource_type == "onedrive":
            results = (
                await client.get_drive_root_children(drive_id)
                if not current_folder_id
                else await client.get_drive_folder_items(
                    drive_id=drive_id, folder_id=current_folder_id
                )
            )
        elif not site_id:
            raise ValueError("site_id required to enumerate SharePoint drive items")
        elif not current_folder_id:
            results = await client.get_drive_root_children(drive_id)
        else:
            results = await client.get_folder_items(
                site_id=site_id, drive_id=drive_id, folder_id=current_folder_id
            )

        for item in results or []:
            item_id = item.get("id")
            if has_graph_facet(item, "folder"):
                if item_id:
                    await _walk(item_id)
            elif item_id:
                items.append(item)

    await _walk(folder_id)

    # Site pages live alongside drive documents for site-root SharePoint scopes.
    if resource_type != "onedrive" and site_id and folder_id is None:
        pages = await client.get_site_pages(site_id=site_id)
        items.extend(page for page in pages.get("value", []) if page.get("id"))

    return items
