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
        logger.info(
            "Infrastructure SharePoint tree service called",
            extra={
                "site_id": site_id,
                "folder_id": folder_id,
                "folder_path": folder_path,
                "has_token": bool(token.access_token),
                "token_id": str(token.id) if token.id else None,
            }
        )

        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
        ) as content_client:
            # Step 1: Get drive ID
            logger.debug("Fetching drive ID for site", extra={"site_id": site_id})
            try:
                drive_id = await content_client.get_default_drive_id(site_id)
                if not drive_id:
                    logger.error(
                        "No drive ID returned for site",
                        extra={"site_id": site_id}
                    )
                    raise ValueError(f"Could not get drive ID for site {site_id}")
                logger.info(
                    "Drive ID obtained",
                    extra={"site_id": site_id, "drive_id": drive_id}
                )
            except Exception as e:
                logger.error(
                    f"Failed to get drive ID: {type(e).__name__}: {str(e)}",
                    extra={"site_id": site_id},
                    exc_info=True
                )
                raise ValueError(f"Failed to get drive ID for site {site_id}: {str(e)}") from e

            if folder_id is None:
                folder_id = "root"
                logger.debug("Using root folder")

            # Step 2: Get folder items
            logger.debug(
                "Fetching folder items",
                extra={
                    "site_id": site_id,
                    "drive_id": drive_id,
                    "folder_id": folder_id,
                }
            )
            try:
                items = await content_client.get_folder_items(
                    site_id=site_id,
                    drive_id=drive_id,
                    folder_id=folder_id,
                )
                logger.info(
                    "Folder items fetched",
                    extra={
                        "item_count": len(items),
                        "folder_id": folder_id,
                    }
                )
            except Exception as e:
                logger.error(
                    f"Failed to get folder items: {type(e).__name__}: {str(e)}",
                    extra={
                        "site_id": site_id,
                        "drive_id": drive_id,
                        "folder_id": folder_id,
                    },
                    exc_info=True
                )
                raise ValueError(
                    f"Failed to fetch folder items for folder {folder_id}: {str(e)}"
                ) from e

            # Step 3: Transform items to tree format
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

            logger.debug(
                "Transformed items to tree format",
                extra={"tree_item_count": len(tree_items)}
            )

            # Step 4: Get parent folder ID if not at root
            parent_id = None
            if folder_id != "root":
                try:
                    logger.debug(
                        "Fetching parent folder metadata",
                        extra={"folder_id": folder_id}
                    )
                    metadata = await content_client.get_file_metadata(
                        drive_id=drive_id,
                        item_id=folder_id,
                    )
                    parent_ref = metadata.get("parentReference", {})
                    parent_id = parent_ref.get("id")
                    logger.debug(
                        "Parent folder ID obtained",
                        extra={"parent_id": parent_id}
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not get parent folder ID: {type(e).__name__}: {str(e)}",
                        extra={"folder_id": folder_id}
                    )

            result = {
                "items": tree_items,
                "current_path": folder_path or "/",
                "parent_id": parent_id,
                "drive_id": drive_id,
                "site_id": site_id,
            }

            logger.info(
                "SharePoint tree successfully built",
                extra={
                    "item_count": len(tree_items),
                    "current_path": result["current_path"],
                    "has_parent": parent_id is not None,
                }
            )

            return result
