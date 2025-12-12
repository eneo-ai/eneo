from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from uuid import UUID

import aiohttp

from intric.integration.infrastructure.content_service.utils import (
    process_sharepoint_response,
)
from intric.libs.clients import BaseClient
from intric.main.logging import get_logger

logger = get_logger(__name__)

TokenRefreshCallback = Callable[[UUID], Awaitable[Dict[str, str]]]


class SharePointContentClient(BaseClient):
    def __init__(
        self,
        base_url: str,
        api_token: str,
        token_id: Optional[UUID] = None,
        token_refresh_callback: Optional[TokenRefreshCallback] = None,
    ):
        super().__init__(base_url=base_url)
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        }
        self.api_token = api_token
        self.token_id = token_id
        # Used to do token refresh when token is expired
        self.token_refresh_callback = token_refresh_callback

    def update_token(self, new_token: str):
        """Update the token and headers with a new token value"""
        self.api_token = new_token
        self.headers = {
            "Authorization": f"Bearer {new_token}",
            "Accept": "application/json",
        }

    async def refresh_token(self):
        """Refresh the token using the provided callback"""
        if not self.token_refresh_callback or not self.token_id:
            raise ValueError(
                "Cannot refresh token: missing token_refresh_callback or token_id"
            )

        token_data = await self.token_refresh_callback(self.token_id)
        if not token_data or "access_token" not in token_data:
            raise ValueError("Token refresh callback returned invalid token data")

        self.update_token(token_data["access_token"])
        return token_data

    async def get_sites(self) -> Dict[str, Any]:
        try:
            return await self.client.get("v1.0/sites?search=*", headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while listing sites, refreshing..."
                )
                await self.refresh_token()
                return await self.client.get(
                    "v1.0/sites?search=*", headers=self.headers
                )
            else:
                raise

    async def get_my_drive(self) -> Dict[str, Any]:
        """Get current user's OneDrive drive info (requires delegated auth)."""
        try:
            return await self.client.get("v1.0/me/drive", headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "Token expired while getting OneDrive, refreshing..."
                )
                await self.refresh_token()
                return await self.client.get("v1.0/me/drive", headers=self.headers)
            else:
                raise

    async def get_drive_root_children(self, drive_id: str) -> Dict[str, Any]:
        """Get items in root of a drive (works for both OneDrive and SharePoint)."""
        endpoint = f"v1.0/drives/{drive_id}/root/children"
        try:
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "Token expired while getting drive root, refreshing..."
                )
                await self.refresh_token()
                return await self.client.get(endpoint, headers=self.headers)
            else:
                raise

    async def get_drive_folder_items(
        self, drive_id: str, folder_id: str
    ) -> List[Dict[str, Any]]:
        """Get items in a folder by drive_id (no site_id needed)."""
        endpoint = f"v1.0/drives/{drive_id}/items/{folder_id}/children"
        try:
            response = await self.client.get(endpoint, headers=self.headers)
            return response.get("value", [])
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "Token expired while getting folder items, refreshing..."
                )
                await self.refresh_token()
                response = await self.client.get(endpoint, headers=self.headers)
                return response.get("value", [])
            else:
                raise

    async def get_site_pages(self, site_id: str) -> Dict[str, Any]:
        try:
            endpoint = f"v1.0/sites/{site_id}/pages"
            page_data = await self.client.get(endpoint, headers=self.headers)
            return page_data

        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                await self.refresh_token()
                page_data = await self.client.get(endpoint, headers=self.headers)
                return page_data
            else:
                logger.error(f"SharePoint API error when getting page content: {e}")
                raise


    async def get_default_drive_id(self, site_id: str) -> Optional[str]:
        """Returnerar default drive-id för sajten (språk-agnostiskt)."""
        try:
            endpoint = f"v1.0/sites/{site_id}/drive"
            resp = await self.client.get(endpoint, headers=self.headers)
            # resp är redan JSON om BaseClient.get() dekodar; annars: resp = await resp.json()
            return resp.get("id")
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                await self.refresh_token()
                resp = await self.client.get(endpoint, headers=self.headers)
                return resp.get("id")
            raise

    async def get_drives(self, site_id: str, drive_name: Optional[str] = None) -> Optional[str]:
        """Returnerar drive-id. Om drive_name är None, välj default documentLibrary deterministiskt."""
        endpoint = f"v1.0/sites/{site_id}/drives"
        try:
            response = await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired when listing drives, refreshing...")
                await self.refresh_token()
                response = await self.client.get(endpoint, headers=self.headers)
            else:
                logger.error(f"Error listing drives: {e}")
                raise

        drives = response.get("value", []) if isinstance(response, dict) else []
        if not drives:
            return None

        if drive_name:
            for d in drives:
                if str(d.get("name", "")).lower() == drive_name.lower():
                    return d.get("id")

        for d in drives:
            if d.get("driveType") == "documentLibrary":
                return d.get("id")

        return await self.get_default_drive_id(site_id)

    async def get_documents_in_drive(self, site_id: str) -> dict:
        try:
            # Språk-agnostiskt: hämta default drive
            drive_id = await self.get_default_drive_id(site_id)
            if not drive_id:
                logger.warning("No drive found for site %s", site_id)
                return {"value": []}

            endpoint = f"v1.0/sites/{site_id}/drives/{drive_id}/root/children"
            response = await self.client.get(endpoint, headers=self.headers)
            return response
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired, refreshing...")
                await self.refresh_token()
                drive_id = await self.get_default_drive_id(site_id)
                if not drive_id:
                    logger.warning("No drive found for site %s after refresh", site_id)
                    return {"value": []}
                endpoint = f"v1.0/sites/{site_id}/drives/{drive_id}/root/children"
                response = await self.client.get(endpoint, headers=self.headers)
                return response
            else:
                logger.error(f"SharePoint API error: {e}")
                raise

    async def get_file_metadata(self, drive_id: str, item_id: str) -> Dict[str, Any]:
        """
        Get metadata for a SharePoint item (file or folder) by its ID.

        Args:
            drive_id: The ID of the drive containing the item
            item_id: The ID of the item

        Returns:
            Dictionary containing the item's metadata
        """
        try:
            endpoint = f"v1.0/drives/{drive_id}/items/{item_id}"
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while getting file metadata, refreshing..."
                )
                await self.refresh_token()

                endpoint = f"v1.0/drives/{drive_id}/items/{item_id}"
                return await self.client.get(endpoint, headers=self.headers)
            else:
                logger.error(f"SharePoint API error when getting file metadata: {e}")
                raise

    async def get_folder_items(
        self,
        site_id: str,
        drive_id: str,
        folder_id: str,
    ) -> List[Dict[str, Any]]:
        """Get items in a folder or the root of a drive.

        Args:
            site_id: The SharePoint site ID
            drive_id: The drive ID
            folder_id: The folder ID

        Returns:
            List of items in the folder
        """
        try:
            endpoint = (
                f"v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
            )
            response = await self.client.get(endpoint, headers=self.headers)
            return response.get("value", [])
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while getting folder items, refreshing..."
                )
                await self.refresh_token()
                endpoint = (
                    f"v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
                )
                response = await self.client.get(endpoint, headers=self.headers)
                return response.get("value", [])
            else:
                logger.error(f"SharePoint API error while getting folder items: {e}")
                raise

    async def get_page_content(self, site_id: str, page_id: str) -> Dict[str, Any]:
        endpoint = f"v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
        try:
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired while getting page content, refreshing...")
                await self.refresh_token()
                return await self.client.get(endpoint, headers=self.headers)
            logger.error(f"SharePoint API error when getting page content: {e}")
            raise

    async def get_file_content_by_id(
        self, drive_id: str, item_id: str
    ) -> Tuple[str, str]:
        """
        Get the content of a file by its ID.

        Args:
            drive_id: The ID of the drive containing the file
            item_id: The ID of the file

        Returns:
            Tuple of (extracted text, content type)
        """
        try:
            file_info = await self.get_file_metadata(drive_id, item_id)
            file_name = file_info.get("name", "")

            download_url = file_info.get("@microsoft.graph.downloadUrl")
            if not download_url:
                return "[Error: No download URL available]", "text/plain"

            async with self.client.client.get(
                download_url, headers=self.headers
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")

                if "application/json" in content_type:
                    data = await response.json()
                    return str(data), content_type
                elif "text/" in content_type or content_type == "application/xml":
                    return await response.text(), content_type
                else:
                    binary_content = await response.read()
                    text, detected_content_type = process_sharepoint_response(
                        response_content=binary_content,
                        content_type=content_type,
                        filename=file_name,
                    )
                    return text, detected_content_type
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while getting file content, refreshing..."
                )
                await self.refresh_token()

                file_info = await self.get_file_metadata(drive_id, item_id)
                file_name = file_info.get("name", "")

                download_url = file_info.get("@microsoft.graph.downloadUrl")
                if not download_url:
                    return (
                        "[Error: No download URL available after token refresh]",
                        "text/plain",
                    )

                url = download_url
                async with self.client.client.get(
                    url, headers=self.headers
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "")

                    if "application/json" in content_type:
                        data = await response.json()
                        return str(data), content_type
                    elif "text/" in content_type or content_type == "application/xml":
                        return await response.text(), content_type
                    else:
                        binary_content = await response.read()
                        text, detected_content_type = process_sharepoint_response(
                            response_content=binary_content,
                            content_type=content_type,
                            filename=file_name,
                        )
                        return text, detected_content_type
            else:
                logger.error(f"SharePoint API error when getting file content: {e}")
                raise

    async def initialize_delta_token(self, drive_id: str) -> Optional[str]:
        """
        Initialize delta tracking for a drive by calling delta without a token.
        Returns the deltaLink token for future incremental syncs.

        Args:
            drive_id: The drive ID to track

        Returns:
            The delta token to use for future incremental syncs, or None if failed
        """
        try:
            endpoint = f"v1.0/drives/{drive_id}/root/delta"

            # Iterate through all pages to get to the final deltaLink
            delta_link = None
            next_link = endpoint

            while next_link:
                # Handle full URL or relative endpoint
                if next_link.startswith("http"):
                    # Extract just the path and query from the full URL
                    from urllib.parse import urlparse
                    parsed = urlparse(next_link)
                    next_link = f"{parsed.path.lstrip('/')}{parsed.query and '?' + parsed.query}"

                response = await self.client.get(next_link, headers=self.headers)

                # Check for @odata.nextLink (more pages to fetch)
                next_link = response.get("@odata.nextLink")

                # Check for @odata.deltaLink (final page with token)
                if "@odata.deltaLink" in response:
                    delta_link = response["@odata.deltaLink"]
                    break

            if not delta_link:
                logger.warning(f"No deltaLink found for drive {drive_id}")
                return None

            # Extract just the token parameter from the deltaLink
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(delta_link)
            query_params = parse_qs(parsed.query)
            token = query_params.get("token", [None])[0]

            if not token:
                logger.warning(f"Could not extract token from deltaLink: {delta_link}")
                return None

            logger.info(f"Initialized delta token for drive {drive_id}")
            return token

        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired during delta init, refreshing...")
                await self.refresh_token()
                return await self.initialize_delta_token(drive_id)
            else:
                logger.error(f"Error initializing delta token: {e}")
                raise

    async def get_delta_changes(
        self, drive_id: str, delta_token: str
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Get changes since the last delta sync using the stored token.

        Args:
            drive_id: The drive ID
            delta_token: The token from the previous sync

        Returns:
            Tuple of (list of changed items, new delta token for next sync)
        """
        try:
            endpoint = f"v1.0/drives/{drive_id}/root/delta?token={delta_token}"

            all_changes = []
            next_link = endpoint
            new_delta_token = None

            while next_link:
                # Handle full URL or relative endpoint
                if next_link.startswith("http"):
                    from urllib.parse import urlparse
                    parsed = urlparse(next_link)
                    next_link = f"{parsed.path.lstrip('/')}{parsed.query and '?' + parsed.query}"

                response = await self.client.get(next_link, headers=self.headers)

                # Collect changed items
                items = response.get("value", [])
                all_changes.extend(items)

                # Check for next page
                next_link = response.get("@odata.nextLink")

                # Check for new delta token
                if "@odata.deltaLink" in response:
                    delta_link = response["@odata.deltaLink"]

                    # Extract token from deltaLink
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(delta_link)
                    query_params = parse_qs(parsed.query)
                    new_delta_token = query_params.get("token", [None])[0]
                    break

            if not new_delta_token:
                logger.warning(f"No new delta token received for drive {drive_id}")
                # Return the old token so we don't lose sync state
                new_delta_token = delta_token

            logger.info(
                f"Retrieved {len(all_changes)} changes for drive {drive_id}"
            )
            return all_changes, new_delta_token

        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired during delta query, refreshing...")
                await self.refresh_token()
                return await self.get_delta_changes(drive_id, delta_token)
            else:
                logger.error(f"Error getting delta changes: {e}")
                raise
