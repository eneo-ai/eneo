import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from uuid import UUID

import aiohttp

from intric.integration.infrastructure.content_service.utils import (
    process_sharepoint_response,
)
from intric.libs.clients import BaseClient
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

TokenRefreshCallback = Callable[[UUID], Awaitable[Dict[str, str]]]


class DeltaTokenExpiredException(Exception):
    """Raised when Microsoft Graph returns 410 Gone for an expired delta token."""

    pass


class SharePointContentClient(BaseClient):
    DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB safety limit
    DEFAULT_GROUP_SITE_CONCURRENCY = 8

    def __init__(
        self,
        base_url: str,
        api_token: str,
        token_id: Optional[UUID] = None,
        token_refresh_callback: Optional[TokenRefreshCallback] = None,
        max_download_bytes: Optional[int] = None,
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
        if max_download_bytes is None:
            self.max_download_bytes = get_settings().sharepoint_max_download_bytes
        else:
            self.max_download_bytes = max_download_bytes

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

    async def _get_all_paged_items(
        self, endpoint: str, headers: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Follow @odata.nextLink pagination and collect all items across pages."""
        from urllib.parse import urlparse

        all_items: List[Dict[str, Any]] = []
        next_link: Optional[str] = endpoint

        while next_link:
            if next_link.startswith("http"):
                parsed = urlparse(next_link)
                next_link = (
                    f"{parsed.path.lstrip('/')}{parsed.query and '?' + parsed.query}"
                )

            response = await self.client.get(next_link, headers=headers or self.headers)
            all_items.extend(response.get("value", []))
            next_link = response.get("@odata.nextLink")

        return all_items

    @staticmethod
    def _parse_content_length(content_length: Optional[str]) -> Optional[int]:
        if not content_length:
            return None
        try:
            return int(content_length)
        except (TypeError, ValueError):
            return None

    async def _read_response_with_size_limit(
        self,
        response: aiohttp.ClientResponse,
        file_name: str,
    ) -> bytes:
        content_length = self._parse_content_length(
            response.headers.get("Content-Length")
        )
        if content_length is not None and content_length > self.max_download_bytes:
            raise ValueError(
                f"SharePoint file '{file_name}' exceeds max download size "
                f"({content_length} > {self.max_download_bytes} bytes)"
            )

        payload = bytearray()
        async for chunk in response.content.iter_chunked(1024 * 1024):
            payload.extend(chunk)
            if len(payload) > self.max_download_bytes:
                raise ValueError(
                    f"SharePoint file '{file_name}' exceeds max download size "
                    f"({len(payload)} > {self.max_download_bytes} bytes)"
                )

        return bytes(payload)

    async def _download_file_content(
        self,
        download_url: str,
        file_name: str,
    ) -> Tuple[str, str]:
        async with self.client.client.get(
            download_url, headers=self.headers
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            content_type_lower = content_type.lower()
            payload = await self._read_response_with_size_limit(response, file_name)

            if "application/json" in content_type_lower:
                decoded = payload.decode(response.charset or "utf-8", errors="replace")
                try:
                    return str(json.loads(decoded)), content_type
                except json.JSONDecodeError:
                    return decoded, content_type

            if "text/" in content_type_lower or "application/xml" in content_type_lower:
                return (
                    payload.decode(response.charset or "utf-8", errors="replace"),
                    content_type,
                )

            text, detected_content_type = process_sharepoint_response(
                response_content=payload,
                content_type=content_type,
                filename=file_name,
            )
            return text, detected_content_type

    async def get_sites(self) -> Dict[str, Any]:
        endpoint = "v1.0/sites?search=*"
        try:
            return {"value": await self._get_all_paged_items(endpoint)}
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while listing sites, refreshing..."
                )
                await self.refresh_token()
                return {"value": await self._get_all_paged_items(endpoint)}
            else:
                raise

    async def get_followed_sites(self) -> List[Dict[str, Any]]:
        """Get sites the current user follows via GET v1.0/me/followedSites."""
        endpoint = "v1.0/me/followedSites"
        try:
            return await self._get_all_paged_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting followed sites, refreshing...")
                await self.refresh_token()
                return await self._get_all_paged_items(endpoint)
            else:
                raise

    async def get_my_unified_groups(self) -> List[Dict[str, Any]]:
        """Get Microsoft 365 (unified) groups the current user is a member of."""
        filtered_endpoint = (
            "v1.0/me/memberOf/microsoft.graph.group"
            "?$filter=groupTypes/any(a:a eq 'Unified')"
            "&$select=id,displayName,groupTypes"
        )
        fallback_endpoint = (
            "v1.0/me/memberOf/microsoft.graph.group?$select=id,displayName,groupTypes"
        )
        headers = {
            **self.headers,
            "ConsistencyLevel": "eventual",
        }

        async def _fetch_groups_with_fallback() -> List[Dict[str, Any]]:
            try:
                return await self._get_all_paged_items(
                    filtered_endpoint, headers=headers
                )
            except aiohttp.ClientResponseError as e:
                # Some tenants reject this cast/filter combo; fall back to client-side
                # filtering so we still discover group-connected sites.
                if e.status not in (400, 501):
                    raise

                logger.info(
                    "Falling back to unfiltered memberOf lookup for unified groups"
                )
                all_groups = await self._get_all_paged_items(
                    fallback_endpoint, headers=headers
                )
                filtered_groups: List[Dict[str, Any]] = []
                for group in all_groups:
                    group_types = group.get("groupTypes")
                    # Some tenants/queries can omit groupTypes; keep such groups and let
                    # /groups/{id}/sites/root determine whether a SharePoint site exists.
                    if group_types is None:
                        filtered_groups.append(group)
                        continue
                    if isinstance(group_types, list) and "Unified" in group_types:
                        filtered_groups.append(group)

                return filtered_groups

        try:
            return await _fetch_groups_with_fallback()
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting groups, refreshing...")
                await self.refresh_token()
                headers["Authorization"] = f"Bearer {self.api_token}"
                return await _fetch_groups_with_fallback()
            raise

    async def get_group_site(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get the root site for a Microsoft 365 group. Returns None if not found."""
        endpoint = f"v1.0/groups/{group_id}/sites/root"
        try:
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status in (404, 403):
                return None
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting group site, refreshing...")
                await self.refresh_token()
                try:
                    return await self.client.get(endpoint, headers=self.headers)
                except aiohttp.ClientResponseError as e2:
                    if e2.status in (404, 403):
                        return None
                    raise
            else:
                raise

    async def get_group_connected_sites(
        self, max_concurrency: int = DEFAULT_GROUP_SITE_CONCURRENCY
    ) -> List[Dict[str, Any]]:
        """Get sites connected to Microsoft 365 groups the user is a member of."""
        groups = await self.get_my_unified_groups()
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def _safe_get_group_site(group_id: str) -> Optional[Dict[str, Any]]:
            async with semaphore:
                try:
                    return await self.get_group_site(group_id)
                except Exception:
                    logger.warning(
                        "Failed to get site for group %s", group_id, exc_info=True
                    )
                    return None

        group_ids = [g["id"] for g in groups if g.get("id")]
        if not group_ids:
            return []

        results = await asyncio.gather(
            *[_safe_get_group_site(group_id) for group_id in group_ids]
        )
        return [site for site in results if site is not None]

    async def get_my_drive(self) -> Dict[str, Any]:
        """Get current user's OneDrive drive info (requires delegated auth)."""
        try:
            return await self.client.get("v1.0/me/drive", headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting OneDrive, refreshing...")
                await self.refresh_token()
                return await self.client.get("v1.0/me/drive", headers=self.headers)
            else:
                raise

    async def get_drive_root_children(self, drive_id: str) -> List[Dict[str, Any]]:
        """Get all items in root of a drive (works for both OneDrive and SharePoint)."""
        endpoint = f"v1.0/drives/{drive_id}/root/children"
        try:
            return await self._get_all_paged_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting drive root, refreshing...")
                await self.refresh_token()
                return await self._get_all_paged_items(endpoint)
            else:
                raise

    async def get_drive_folder_items(
        self, drive_id: str, folder_id: str
    ) -> List[Dict[str, Any]]:
        """Get all items in a folder by drive_id (no site_id needed)."""
        endpoint = f"v1.0/drives/{drive_id}/items/{folder_id}/children"
        try:
            return await self._get_all_paged_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("Token expired while getting folder items, refreshing...")
                await self.refresh_token()
                return await self._get_all_paged_items(endpoint)
            else:
                raise

    async def get_site_pages(self, site_id: str) -> Dict[str, Any]:
        endpoint = f"v1.0/sites/{site_id}/pages"
        try:
            return {"value": await self._get_all_paged_items(endpoint)}

        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                await self.refresh_token()
                return {"value": await self._get_all_paged_items(endpoint)}
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

    async def get_drives(
        self, site_id: str, drive_name: Optional[str] = None
    ) -> Optional[str]:
        """Returnerar drive-id. Om drive_name är None, välj default documentLibrary deterministiskt."""
        endpoint = f"v1.0/sites/{site_id}/drives"
        try:
            response = await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired when listing drives, refreshing..."
                )
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

    async def get_documents_in_drive(self, site_id: str) -> List[Dict[str, Any]]:
        try:
            drive_id = await self.get_default_drive_id(site_id)
            if not drive_id:
                logger.warning("No drive found for site %s", site_id)
                return []

            endpoint = f"v1.0/sites/{site_id}/drives/{drive_id}/root/children"
            return await self._get_all_paged_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info("SharePoint token expired, refreshing...")
                await self.refresh_token()
                drive_id = await self.get_default_drive_id(site_id)
                if not drive_id:
                    logger.warning("No drive found for site %s after refresh", site_id)
                    return []
                endpoint = f"v1.0/sites/{site_id}/drives/{drive_id}/root/children"
                return await self._get_all_paged_items(endpoint)
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
            return await self._get_all_paged_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while getting folder items, refreshing..."
                )
                await self.refresh_token()
                endpoint = (
                    f"v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
                )
                return await self._get_all_paged_items(endpoint)
            else:
                logger.error(f"SharePoint API error while getting folder items: {e}")
                raise

    async def get_page_content(self, site_id: str, page_id: str) -> Dict[str, Any]:
        endpoint = f"v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
        try:
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.token_refresh_callback and self.token_id:
                logger.info(
                    "SharePoint token expired while getting page content, refreshing..."
                )
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

            return await self._download_file_content(
                download_url=download_url,
                file_name=file_name,
            )
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

                return await self._download_file_content(
                    download_url=download_url,
                    file_name=file_name,
                )
            else:
                logger.error(f"SharePoint API error when getting file content: {e}")
                raise

    async def initialize_delta_token(self, drive_id: str, *, _retried: bool = False) -> Optional[str]:
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
            if e.status == 410:
                raise DeltaTokenExpiredException(
                    f"Delta token expired (410 Gone) during initialization for drive {drive_id}"
                ) from e
            elif e.status == 401 and self.token_refresh_callback and self.token_id and not _retried:
                logger.info("SharePoint token expired during delta init, refreshing...")
                await self.refresh_token()
                return await self.initialize_delta_token(drive_id, _retried=True)
            else:
                logger.error(f"Error initializing delta token: {e}")
                raise

    async def get_delta_changes(
        self, drive_id: str, delta_token: str, *, _retried: bool = False
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

            logger.info(f"Retrieved {len(all_changes)} changes for drive {drive_id}")
            return all_changes, new_delta_token

        except aiohttp.ClientResponseError as e:
            if e.status == 410:
                raise DeltaTokenExpiredException(
                    f"Delta token expired (410 Gone) for drive {drive_id}"
                ) from e
            elif e.status == 401 and self.token_refresh_callback and self.token_id and not _retried:
                logger.info(
                    "SharePoint token expired during delta query, refreshing..."
                )
                await self.refresh_token()
                return await self.get_delta_changes(drive_id, delta_token, _retried=True)
            else:
                logger.error(f"Error getting delta changes: {e}")
                raise
