from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, cast
from uuid import UUID

from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
    extract_source_metadata,
)
from eneo.integration.infrastructure.preview_service.sharepoint_search import (
    MAX_SEARCH_RESULTS,
    build_odata_filter,
    clean_search_text,
    filter_columns,
    row_from_drive_item,
    row_from_list_item,
    row_matches,
)
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

TokenRefreshCallback = Callable[[UUID], Awaitable[Dict[str, str]]]


class SharePointTreeService:
    def __init__(
        self, token_refresh_callback: Optional[TokenRefreshCallback] = None
    ) -> None:
        super().__init__()
        self.token_refresh_callback = token_refresh_callback

    async def get_folder_tree(
        self,
        token: SharePointToken,
        site_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        folder_path: str = "",
    ) -> Dict[str, Any]:
        """
        Get folder tree for SharePoint site or OneDrive.

        Args:
            token: SharePoint OAuth token
            site_id: SharePoint site ID (required for SharePoint sites)
            drive_id: Direct drive ID (required for OneDrive, optional for SharePoint)
            folder_id: Folder ID to browse (defaults to root)
            folder_path: Current folder path for display

        Returns:
            Tree structure with items, path info, and drive/site IDs
        """
        if not site_id and not drive_id:
            raise ValueError("Either site_id or drive_id must be provided")

        logger.info(
            "Infrastructure SharePoint tree service called",
            extra={
                "site_id": site_id,
                "drive_id": drive_id,
                "folder_id": folder_id,
                "folder_path": folder_path,
                "has_token": bool(token.access_token),
                "token_id": str(token.id) if token.id else None,
            },
        )

        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
            # Files in the picker show the library columns that will follow
            # them on import, so people can see what is searchable before
            # choosing.
            include_list_item_fields=True,
        ) as content_client:
            actual_drive_id = drive_id
            if not actual_drive_id and site_id:
                logger.debug("Fetching drive ID for site", extra={"site_id": site_id})
                try:
                    actual_drive_id = await content_client.get_default_drive_id(site_id)
                    if not actual_drive_id:
                        logger.error(
                            "No drive ID returned for site", extra={"site_id": site_id}
                        )
                        raise ValueError(f"Could not get drive ID for site {site_id}")
                    logger.info(
                        "Drive ID obtained",
                        extra={"site_id": site_id, "drive_id": actual_drive_id},
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to get drive ID: {type(e).__name__}: {str(e)}",
                        extra={"site_id": site_id},
                        exc_info=True,
                    )
                    raise ValueError(
                        f"Failed to get drive ID for site {site_id}: {str(e)}"
                    ) from e
            else:
                logger.info(
                    "Using provided drive ID directly (OneDrive)",
                    extra={"drive_id": actual_drive_id},
                )

            if actual_drive_id is None:
                raise ValueError("Could not resolve drive ID")

            if folder_id is None:
                folder_id = "root"
                logger.debug("Using root folder")

            logger.debug(
                "Fetching folder items",
                extra={
                    "site_id": site_id,
                    "drive_id": actual_drive_id,
                    "folder_id": folder_id,
                },
            )
            try:
                if site_id:
                    items = await content_client.get_folder_items(
                        site_id=site_id,
                        drive_id=actual_drive_id,
                        folder_id=folder_id,
                    )
                else:
                    if folder_id == "root":
                        items = await content_client.get_drive_root_children(
                            actual_drive_id
                        )
                    else:
                        items = await content_client.get_drive_folder_items(
                            drive_id=actual_drive_id,
                            folder_id=folder_id,
                        )
                logger.info(
                    "Folder items fetched",
                    extra={
                        "item_count": len(items),
                        "folder_id": folder_id,
                    },
                )
            except Exception as e:
                logger.error(
                    f"Failed to get folder items: {type(e).__name__}: {str(e)}",
                    extra={
                        "site_id": site_id,
                        "drive_id": actual_drive_id,
                        "folder_id": folder_id,
                    },
                    exc_info=True,
                )
                raise ValueError(
                    f"Failed to fetch folder items for folder {folder_id}: {str(e)}"
                ) from e

            # The root listing always needs the columns (they drive the filter
            # menu); a subfolder only when it holds files whose properties are
            # read, so opening folder after folder does not repeat the request.
            has_files = any(item.get("folder") is None for item in items)
            catalog = (
                await self._column_catalog(content_client, actual_drive_id)
                if folder_id == "root" or has_files
                else SharePointColumnCatalog()
            )

            tree_items: List[Dict[str, Any]] = []
            for item in items:
                item_name = item.get("name", "")
                item_id = item.get("id", "")
                is_folder = item.get("folder") is not None
                item_path = (
                    f"{folder_path}/{item_name}" if folder_path else f"/{item_name}"
                )
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
                    "source_metadata": (
                        []
                        if is_folder
                        else extract_source_metadata(
                            cast(Dict[str, Any], item), catalog
                        )
                    ),
                }
                tree_items.append(tree_item)

            logger.debug(
                "Transformed items to tree format",
                extra={"tree_item_count": len(tree_items)},
            )

            parent_id = None
            if folder_id != "root":
                try:
                    logger.debug(
                        "Fetching parent folder metadata",
                        extra={"folder_id": folder_id},
                    )
                    metadata = await content_client.get_file_metadata(
                        drive_id=actual_drive_id,
                        item_id=folder_id,
                    )
                    parent_ref = metadata.get("parentReference", {})
                    parent_id = parent_ref.get("id")
                    logger.debug(
                        "Parent folder ID obtained", extra={"parent_id": parent_id}
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not get parent folder ID: {type(e).__name__}: {str(e)}",
                        extra={"folder_id": folder_id},
                    )

            result: Dict[str, Any] = {
                "items": tree_items,
                "current_path": folder_path or "/",
                "parent_id": parent_id,
                "drive_id": actual_drive_id,
                "site_id": site_id,
                "columns": filter_columns(catalog),
            }

            logger.info(
                "SharePoint tree successfully built",
                extra={
                    "item_count": len(tree_items),
                    "current_path": result["current_path"],
                    "has_parent": parent_id is not None,
                },
            )

            return result

    async def search_library(
        self,
        token: SharePointToken,
        site_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        text: str = "",
        filters: Optional[Dict[str, str]] = None,
        max_items: int = MAX_SEARCH_RESULTS,
    ) -> Dict[str, Any]:
        """Files anywhere in the library matching ``text`` and column ``filters``.

        Column filters go to Graph as a list query so the whole library is
        covered without browsing it. Free text alone uses Graph's drive search,
        which also looks inside documents. With both, the column query runs and
        the text is checked against the rows that come back.
        """
        if not site_id and not drive_id:
            raise ValueError("Either site_id or drive_id must be provided")
        text = clean_search_text(text)
        filters = {k: v for k, v in (filters or {}).items() if v.strip()}
        if not text and not filters:
            return {
                "items": [],
                "truncated": False,
                "drive_id": drive_id,
                "site_id": site_id,
            }

        async with SharePointContentClient(
            base_url=token.base_url,
            api_token=token.access_token,
            token_id=token.id,
            token_refresh_callback=self.token_refresh_callback,
            include_list_item_fields=True,
        ) as content_client:
            actual_drive_id = drive_id
            if not actual_drive_id and site_id:
                actual_drive_id = await content_client.get_default_drive_id(site_id)
            if not actual_drive_id:
                raise ValueError("Could not resolve drive ID")

            catalog = await self._column_catalog(content_client, actual_drive_id)
            odata_filter, residual = build_odata_filter(catalog, filters)
            if residual:
                # A column Graph cannot compare would turn the query into a
                # capped listing of the whole library, checked locally.
                raise ValueError(
                    "Unknown filter column: " + ", ".join(sorted(residual))
                )

            rows: List[Dict[str, Any]] = []
            truncated = False
            if filters:
                # The free text is checked locally on the column query's rows;
                # the client keeps paging until enough rows pass, so a match
                # past the first page is not lost.
                accepted: List[Dict[str, Any]] = []

                def accept(raw: Dict[str, Any]) -> bool:
                    row = row_from_list_item(raw, catalog)
                    if row is None or not row_matches(row, text, {}):
                        return False
                    accepted.append(row)
                    return True

                _, truncated = await content_client.get_list_items_filtered(
                    actual_drive_id, odata_filter, max_items=max_items, accept=accept
                )
                rows = accepted[:max_items]
            else:
                raw_rows, truncated = await content_client.search_drive_items(
                    actual_drive_id, text, max_items=max_items
                )
                for raw in raw_rows:
                    row = row_from_drive_item(raw, catalog)
                    if row:
                        rows.append(row)

            logger.info(
                "SharePoint library search done",
                extra={
                    "drive_id": actual_drive_id,
                    "filters": sorted(filters),
                    "has_text": bool(text),
                    "result_count": len(rows),
                    "truncated": truncated,
                },
            )
            return {
                "items": rows,
                "truncated": truncated,
                "drive_id": actual_drive_id,
                "site_id": site_id,
            }

    @staticmethod
    async def _column_catalog(
        content_client: SharePointContentClient, drive_id: str
    ) -> SharePointColumnCatalog:
        """The library's admitted columns; empty when they cannot be read.

        Browsing must not fail because a drive has no backing list (personal
        OneDrive) or the token lacks list access: the tree is simply shown
        without properties, as the import would store it.
        """
        if not content_client.list_item_fields_enabled:
            return SharePointColumnCatalog()
        try:
            definitions = await content_client.get_list_columns(drive_id)
        except Exception as e:  # noqa: BLE001 - enrichment only
            logger.warning(
                "Could not read library columns for drive %s while browsing: %s",
                drive_id,
                e,
            )
            return SharePointColumnCatalog()
        return SharePointColumnCatalog.from_graph(definitions)
