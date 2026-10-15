"""A SharePoint content client that serves a local folder.

Subclasses the real client and replaces only what touches Microsoft Graph:
listing is a directory walk and a download is a file read. Everything after
the bytes arrive (text extraction, byte retention, the sync's publishing
rules) runs through production code, so a sync against a folder exercises
the same path as a sync against a tenant. Full syncs only.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.originals import (
    retain_original_bytes,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointFileContent,
    SharePointItem,
)
from eneo.integration.infrastructure.content_service.utils import (
    process_sharepoint_response,
    sync_index_text,
)

FIXTURE_DRIVE_ID = "fixture-drive"
FIXTURE_ROOT_ID = "fixture-root"
FIXTURE_WEB_ORIGIN = "https://sharepoint.invalid"


class LocalFolderSharePointClient(SharePointContentClient):
    """The real client over a directory instead of a Graph drive."""

    def __init__(self, root: Path, **_ignored: Any) -> None:
        super().__init__(base_url=FIXTURE_WEB_ORIGIN, api_token="fixture")
        self.root = Path(root)

    # --- identifiers -------------------------------------------------------

    def _item_id(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")

    def _path(self, item_id: str) -> Path:
        if item_id in (FIXTURE_ROOT_ID, ""):
            return self.root
        candidate = (self.root / item_id).resolve()
        if self.root.resolve() not in candidate.parents and candidate != self.root:
            raise ValueError(f"Item {item_id!r} is outside the fixture folder")
        return candidate

    def _item(self, path: Path) -> SharePointItem:
        stat = path.stat()
        item: SharePointItem = {
            "id": self._item_id(path),
            "name": path.name,
            "webUrl": f"{FIXTURE_WEB_ORIGIN}/{self._item_id(path)}",
            "size": stat.st_size,
            "lastModifiedDateTime": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "parentReference": {"driveId": FIXTURE_DRIVE_ID},
        }
        if path.is_dir():
            item["folder"] = {"childCount": sum(1 for _ in path.iterdir())}
        else:
            item["file"] = {
                "mimeType": mimetypes.guess_type(path.name)[0]
                or "application/octet-stream"
            }
        return item

    def _children(self, folder: Path) -> list[SharePointItem]:
        return [
            self._item(child)
            for child in sorted(folder.iterdir())
            if not child.name.startswith(".")
        ]

    # --- listing -----------------------------------------------------------

    async def get_default_drive_id(self, site_id: str) -> str | None:
        return FIXTURE_DRIVE_ID

    async def get_drive_root_children(self, drive_id: str) -> list[SharePointItem]:
        return self._children(self.root)

    async def get_drive_folder_items(
        self, drive_id: str, folder_id: str
    ) -> list[SharePointItem]:
        return self._children(self._path(folder_id))

    async def get_folder_items(
        self, site_id: str | None, drive_id: str, folder_id: str
    ) -> list[SharePointItem]:
        return self._children(self._path(folder_id))

    async def get_documents_in_drive(self, site_id: str) -> list[SharePointItem]:
        return self._children(self.root)

    async def get_site_pages(self, site_id: str) -> dict[str, list[SharePointItem]]:
        return {"value": []}

    async def get_list_columns(self, drive_id: str) -> list[dict[str, Any]]:
        return []

    async def get_file_metadata(self, drive_id: str, item_id: str) -> dict[str, Any]:
        path = self._path(item_id)
        item: dict[str, Any] = dict(self._item(path))
        item["@microsoft.graph.downloadUrl"] = path.as_uri()
        return item

    # --- content -----------------------------------------------------------

    async def _download_file_content(
        self, download_url: str, file_name: str
    ) -> SharePointFileContent:
        path = Path(download_url.removeprefix("file://"))
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        data = payload if retain_original_bytes(file_name, content_type) else None
        if content_type.startswith("text/"):
            text, detected = payload.decode("utf-8", errors="replace"), content_type
        else:
            text, detected = process_sharepoint_response(
                response_content=payload, content_type=content_type, filename=file_name
            )
        return SharePointFileContent(
            text=text,
            content_type=detected,
            file_name=file_name,
            data=data,
            index_text=sync_index_text(file_name, text, retained=data is not None),
        )

    # --- delta: full syncs only -------------------------------------------

    async def initialize_delta_token(self, drive_id: str, **_kwargs: Any) -> str:
        return "fixture-delta-token"

    async def get_delta_changes(self, *_args: Any, **_kwargs: Any):
        raise NotImplementedError("The local folder client supports full syncs only")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None
