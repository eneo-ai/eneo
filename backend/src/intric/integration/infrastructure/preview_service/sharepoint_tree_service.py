from typing import TYPE_CHECKING, Optional, Callable, Awaitable, Dict
from uuid import UUID

from intric.integration.domain.entities.oauth_token import SharePointToken
from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

TokenRefreshCallback = Callable[[UUID], Awaitable[Dict[str, str]]]


class SharePointTreeService:
    def __init__(self, token_refresh_callback: Optional[TokenRefreshCallback] = None):
        self.token_refresh_callback = token_refresh_callback

    async def get_folder_tree(
        self,
        token: SharePointToken,
        site_id: str,
        folder_id: Optional[str] = None,
        folder_path: str = "",
    ) -> dict:
        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as content_client:
            drive_id = await content_client.get_default_drive_id(site_id)
            if not drive_id:
                logger.error(f"Could not get drive ID for site {site_id}")
                raise ValueError(f"Could not get drive ID for site {site_id}")

            if folder_id is None:
                folder_id = "root"

            items = await content_client.get_folder_items(
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )

            tree_items = []
            for item in items:
                item_name = item.get("name", "")
                item_id = item.get("id", "")
                is_folder = item.get("folder") is not None
                item_path = f"{folder_path}/{item_name}" if folder_path else f"/{item_name}"
                size = item.get("size")
                modified = item.get("lastModifiedDateTime")
                web_url = item.get("webUrl", "")

                tree_item = {
                    "id": item_id,
                    "name": item_name,
                    "type": "folder" if is_folder else "file",
                    "path": item_path,
                    "has_children": is_folder,
                    "size": size,
                    "modified": modified,
                    "web_url": web_url,
                }
                tree_items.append(tree_item)

            parent_id = None
            if folder_id != "root":
                try:
                    metadata = await content_client.get_file_metadata(
                        drive_id=drive_id,
                        item_id=folder_id,
                    )
                    parent_ref = metadata.get("parentReference", {})
                    parent_id = parent_ref.get("id")
                except Exception as e:
                    logger.warning(f"Could not get parent folder ID: {e}")

            return {
                "items": tree_items,
                "current_path": folder_path or "/",
                "parent_id": parent_id,
                "drive_id": drive_id,
                "site_id": site_id,
            }
