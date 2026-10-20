import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence, cast
from urllib.parse import ParseResult, quote, unquote, urlparse
from uuid import UUID

import aiohttp
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy

from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    LIST_ITEM_FIELDS_EXPAND,
)
from eneo.integration.infrastructure.content_service.types import SharePointItem
from eneo.integration.infrastructure.content_service.utils import (
    ExtractionResult,
    extract_sharepoint_content,
)
from eneo.libs.clients import BaseClient
from eneo.libs.clients.throttle_retry import (
    THROTTLE_AND_OVERLOAD_STATUS_CODES,
    TRANSIENT_STATUS_CODES,
    parse_retry_after,
    retry_on_throttle,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

TokenRefreshCallback = Callable[[UUID], Awaitable[dict[str, str]]]
# Re-acquires an organisation (tenant app / service account) access token, which
# has no OAuth token row and so no token id to hand to a TokenRefreshCallback.
AccessTokenProvider = Callable[[], Awaitable[str]]


# Without it a delta page also lists the parent chain of every changed item.
DELTA_REQUEST_HEADERS: dict[str, str] = {"Prefer": "deltaExcludeParent"}


def _relative_graph_link(url: str) -> str:
    """Reduce an absolute Graph URL to the relative path+query the client expects."""
    parsed: ParseResult = urlparse(url)
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.path.lstrip('/')}{query}"


def _strip_query_param(url: str, name: str) -> str:
    """Remove one query parameter from a relative or absolute URL."""
    if "?" not in url:
        return url
    path, _, query = url.partition("?")
    encoded = name.replace("$", "%24")
    kept = [
        part
        for part in query.split("&")
        if part and part.split("=", 1)[0] not in (name, encoded)
    ]
    return f"{path}?{'&'.join(kept)}" if kept else path


def _token_from_delta_link(delta_link: str) -> Optional[str]:
    """The token as Graph encoded it: a ``+`` in it is a plus, not a space."""
    for part in urlparse(delta_link).query.split("&"):
        name, _, value = part.partition("=")
        if name == "token":
            return unquote(value) or None
    return None


def _without_download_credentials(
    error: aiohttp.ClientResponseError,
) -> aiohttp.ClientResponseError:
    """The same error without the URL query and the request headers.

    A download URL is pre-authenticated: its query holds a bearer token
    (``tempauth``), which aiohttp puts in the error text. The request headers
    go too, so no credential can reach a log through them. Status and response
    headers stay for the throttling and token-refresh handling.
    """
    info = error.request_info
    return aiohttp.ClientResponseError(
        RequestInfo(
            info.url.with_query(None).with_fragment(None),
            info.method,
            CIMultiDictProxy(CIMultiDict[str]()),
            info.real_url.with_query(None).with_fragment(None),
        ),
        (),
        status=error.status,
        message=error.message,
        headers=error.headers,
    )


def _without_query(url: str) -> str:
    return re.split(r"[?#]", url, maxsplit=1)[0]


class IncompleteDownloadError(aiohttp.ClientPayloadError):
    """The body ended before the announced Content-Length.

    Partial bytes must never be parsed: a truncated PDF or ZIP looks like a
    corrupt or empty file and would be mistaken for one. A payload error, so
    the download is retried like any other cut-off transfer.
    """


class MissingDownloadUrlError(ValueError):
    """Graph returned the item without a download URL.

    Either for good (some item kinds have no content stream) or for now (a
    file being uploaded or processed), so callers must not treat it as a
    verdict about the file's content.
    """


class DeltaTokenExpiredException(Exception):
    """Raised when Microsoft Graph returns 410 Gone for an expired delta token."""

    pass


@dataclass(frozen=True)
class SharePointItemLookup:
    """An item-level Graph answer, distinct from a failed batch request."""

    status: int
    item: SharePointItem | None = None


class SharePointContentClient(BaseClient):
    DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB safety limit
    BATCH_SIZE = 20  # Microsoft Graph JSON-batching maximum
    BATCH_CONCURRENCY = 4
    BATCH_MAX_RETRY_ROUNDS = 3
    BATCH_MIN_RETRY_SLEEP_SECONDS = 2.0
    BATCH_MAX_RETRY_SLEEP_SECONDS = 60.0

    def __init__(
        self,
        base_url: str,
        api_token: str,
        token_id: Optional[UUID] = None,
        token_refresh_callback: Optional[TokenRefreshCallback] = None,
        max_download_bytes: Optional[int] = None,
        include_list_item_fields: bool = False,
        access_token_provider: Optional[AccessTokenProvider] = None,
    ):
        super().__init__(base_url=base_url)
        # Content sync asks for each item's list item columns (source metadata)
        # in the same listing and delta calls. Browsing for the import picker
        # does not: the expansion makes every page heavier for nothing there.
        # Cleared for the rest of this client's life if Graph rejects the
        # expansion, so one odd drive degrades to plain listings, not failure.
        self._list_item_expand_enabled = include_list_item_fields
        self.headers: dict[str, str] = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        }
        self.api_token = api_token
        self.token_id = token_id
        # Used to do token refresh when token is expired
        self.token_refresh_callback = token_refresh_callback
        self.access_token_provider = access_token_provider
        # Serializes refreshes when concurrent requests hit 401 simultaneously.
        self._refresh_lock = asyncio.Lock()
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

    @property
    def can_refresh_token(self) -> bool:
        return self.access_token_provider is not None or bool(
            self.token_refresh_callback and self.token_id
        )

    async def refresh_token(self):
        """Refresh the token using the provided callback"""
        if not self.can_refresh_token:
            raise ValueError(
                "Cannot refresh token: missing token_refresh_callback or token_id"
            )

        token_before = self.api_token
        async with self._refresh_lock:
            if self.api_token != token_before:
                # Another concurrent caller already refreshed.
                return None

            if self.access_token_provider is not None:
                access_token = await self.access_token_provider()
                if not access_token:
                    raise ValueError("Access token provider returned no token")
                self.update_token(access_token)
                return {"access_token": access_token}

            if self.token_refresh_callback is None or self.token_id is None:
                raise ValueError(
                    "Cannot refresh token: missing token_refresh_callback or token_id"
                )
            token_data = await self.token_refresh_callback(self.token_id)
            if not token_data or "access_token" not in token_data:
                raise ValueError("Token refresh callback returned invalid token data")

            self.update_token(token_data["access_token"])
            return token_data

    async def _get_all_paged_items(self, endpoint: str) -> list[SharePointItem]:
        """Follow @odata.nextLink pagination and collect all items across pages."""
        all_items: list[SharePointItem] = []
        next_link: Optional[str] = endpoint

        while next_link:
            if next_link.startswith("http"):
                next_link = _relative_graph_link(next_link)

            response = await self.client.get(next_link, headers=self.headers)
            all_items.extend(response.get("value", []))
            next_link = response.get("@odata.nextLink")

        return all_items

    @property
    def list_item_fields_enabled(self) -> bool:
        return self._list_item_expand_enabled

    def _with_item_expand(self, endpoint: str) -> str:
        if not self._list_item_expand_enabled:
            return endpoint
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}$expand={LIST_ITEM_FIELDS_EXPAND}"

    def _disable_item_expand_after(self, error: aiohttp.ClientResponseError) -> bool:
        """True when the failed request should be retried without the expansion.

        Graph answers 400 for an ``$expand`` it cannot honour (for example on
        drives without a backing list). Everything else is not about the
        expansion and propagates as before.
        """
        if not self._list_item_expand_enabled or error.status != 400:
            return False
        self._list_item_expand_enabled = False
        logger.warning(
            "Graph rejected $expand=%s (%s); continuing without source metadata "
            "for the rest of this sync",
            LIST_ITEM_FIELDS_EXPAND,
            error.message,
        )
        return True

    async def _get_items(self, endpoint: str) -> list[SharePointItem]:
        """Paged listing with list item columns when enabled."""
        try:
            return await self._get_all_paged_items(self._with_item_expand(endpoint))
        except aiohttp.ClientResponseError as e:
            if self._disable_item_expand_after(e):
                return await self._get_all_paged_items(endpoint)
            raise

    async def _get_item(self, endpoint: str) -> dict[str, Any]:
        """Single item with list item columns when enabled."""
        try:
            return await self.client.get(
                self._with_item_expand(endpoint), headers=self.headers
            )
        except aiohttp.ClientResponseError as e:
            if self._disable_item_expand_after(e):
                return await self.client.get(endpoint, headers=self.headers)
            raise

    # Rows Graph is asked for before a search gives up on finding more matches
    # when file or column checks discard most of the returned rows.
    MAX_SCANNED_ROWS = 2000

    async def _get_paged_items_capped(
        self,
        endpoint: str,
        *,
        max_items: int,
        headers: Optional[dict[str, str]] = None,
        accept: Optional[Callable[[dict[str, object]], bool]] = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Pages until ``max_items`` accepted rows are in hand.

        ``accept`` drops rows as they arrive, so the cap counts matches rather
        than raw rows. The second value is True when more matches may exist:
        another page remained, or the scan budget ran out first.
        """
        rows: list[dict[str, Any]] = []
        scanned = 0
        next_link: Optional[str] = endpoint
        while next_link:
            if next_link.startswith("http"):
                next_link = _relative_graph_link(next_link)
            response = await self.client.get(
                next_link, headers={**self.headers, **(headers or {})}
            )
            page = cast(list[dict[str, Any]], response.get("value", []))
            scanned += len(page)
            for row in page:
                if accept is None or accept(row):
                    rows.append(row)
            next_link = cast(Optional[str], response.get("@odata.nextLink"))
            if len(rows) >= max_items:
                return rows[:max_items], bool(next_link) or len(rows) > max_items
            if next_link and scanned >= max(self.MAX_SCANNED_ROWS, max_items):
                return rows, True
        return rows, False

    async def _get_items_capped(
        self, endpoint: str, *, max_items: int
    ) -> tuple[list[SharePointItem], bool]:
        """Capped paged listing with list item columns when enabled."""
        try:
            rows, truncated = await self._get_paged_items_capped(
                self._with_item_expand(endpoint), max_items=max_items
            )
        except aiohttp.ClientResponseError as e:
            if not self._disable_item_expand_after(e):
                raise
            rows, truncated = await self._get_paged_items_capped(
                endpoint, max_items=max_items
            )
        return cast(list[SharePointItem], rows), truncated

    async def list_folder_children(
        self,
        *,
        drive_id: str,
        folder_id: str,
        site_id: Optional[str] = None,
        max_items: int,
    ) -> tuple[list[SharePointItem], bool]:
        """Up to ``max_items`` children of a folder; True when more exist.

        For the picker: a folder with thousands of items is cut off here and
        reported as truncated, so people search instead of scrolling a list
        Graph would take minutes to page through.
        """
        if site_id:
            endpoint = (
                f"v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
            )
        elif folder_id == "root":
            endpoint = f"v1.0/drives/{drive_id}/root/children"
        else:
            endpoint = f"v1.0/drives/{drive_id}/items/{folder_id}/children"
        try:
            return await self._get_items_capped(endpoint, max_items=max_items)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "Token expired while listing folder children, refreshing..."
                )
                await self.refresh_token()
                return await self._get_items_capped(endpoint, max_items=max_items)
            raise

    async def get_list_items_filtered(
        self,
        drive_id: str,
        odata_filter: Optional[str],
        *,
        max_items: int,
        accept: Optional[Callable[[dict[str, object]], bool]] = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """List items of a library with their columns and drive item.

        ``odata_filter`` compares a single indexed ``fields/<Column>``.
        ``accept`` keeps paging past rows a local check rejects.
        """
        endpoint = f"v1.0/drives/{drive_id}/list/items?$expand=fields,driveItem"
        if odata_filter:
            # A column value may hold &, # or %, which would otherwise end or
            # corrupt the query string.
            endpoint += "&$filter=" + quote(odata_filter, safe="/")
        try:
            return await self._get_paged_items_capped(
                endpoint, max_items=max_items, accept=accept
            )
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                await self.refresh_token()
                return await self._get_paged_items_capped(
                    endpoint, max_items=max_items, accept=accept
                )
            raise

    async def search_drive_items(
        self,
        drive_id: str,
        text: str,
        *,
        max_items: int,
        accept: Optional[Callable[[dict[str, object]], bool]] = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Drive items whose name or content matches ``text``, with list item columns when enabled."""
        # Percent-encoded inside the path segment, so quotes, &, # and spaces
        # in what a person typed reach Graph as the search text.
        quoted = quote(text.replace("'", "''"), safe="")
        endpoint = self._with_item_expand(
            f"v1.0/drives/{drive_id}/root/search(q='{quoted}')"
        )
        try:
            return await self._get_paged_items_capped(
                endpoint, max_items=max_items, accept=accept
            )
        except aiohttp.ClientResponseError as e:
            if self._disable_item_expand_after(e):
                return await self._get_paged_items_capped(
                    _strip_query_param(endpoint, "$expand"),
                    max_items=max_items,
                    accept=accept,
                )
            if e.status == 401 and self.can_refresh_token:
                await self.refresh_token()
                return await self._get_paged_items_capped(
                    endpoint, max_items=max_items, accept=accept
                )
            raise

    async def get_list_columns(self, drive_id: str) -> list[dict[str, Any]]:
        """Column definitions of the list behind a document library."""
        endpoint = f"v1.0/drives/{drive_id}/list/columns"
        try:
            return cast(list[dict[str, Any]], await self._get_all_paged_items(endpoint))
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info("Token expired while getting list columns, refreshing...")
                await self.refresh_token()
                return cast(
                    list[dict[str, Any]], await self._get_all_paged_items(endpoint)
                )
            raise

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

        # aiohttp hands back the decompressed body while Content-Length counts
        # the wire bytes, so the two only agree for an unencoded body.
        encoding = response.headers.get("Content-Encoding", "").strip().lower()
        if encoding in ("", "identity"):
            if content_length is not None and len(payload) != content_length:
                raise IncompleteDownloadError(
                    f"Incomplete download of '{file_name}' "
                    f"({len(payload)} of {content_length} bytes)"
                )

        return bytes(payload)

    async def _download_file_content(
        self,
        download_url: str,
        file_name: str,
    ) -> ExtractionResult:
        # Streams the body directly off the raw session to enforce the size
        # limit, bypassing WrappedAiohttpClient — so the retry is applied here
        # explicitly. Extraction runs once, after the transfer succeeded.
        async def _download() -> tuple[bytes, str, Optional[str]]:
            # The status check raises, and so does the request itself, for
            # example after too many redirects or at an invalid redirect. from
            # None: a traceback must not show the original either.
            # No Authorization header: the URL authorizes itself (tempauth),
            # and the Graph token must not reach the host that serves it.
            try:
                async with self.client.client.get(download_url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "")
                    charset = response.charset
                    payload = await self._read_response_with_size_limit(
                        response, file_name
                    )
            except aiohttp.ClientResponseError as e:
                raise _without_download_credentials(e) from None
            except aiohttp.InvalidURL as e:
                raise aiohttp.InvalidURL(
                    _without_query(str(e.url)), e.description
                ) from None
            return payload, content_type, charset

        # A body still cut off after the retries propagates: it says nothing
        # about the file, so the caller keeps the copy and tries again later.
        payload, content_type, charset = await retry_on_throttle(
            _download,
            retryable_status_codes=TRANSIENT_STATUS_CODES,
            retry_transport_errors=True,
        )

        return await extract_sharepoint_content(
            payload, content_type, file_name, charset=charset
        )

    async def get_sites(self) -> dict[str, Any]:
        endpoint = "v1.0/sites?search=*&$select=id,displayName,webUrl"
        try:
            return {"value": await self._get_all_paged_items(endpoint)}
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while listing sites, refreshing..."
                )
                await self.refresh_token()
                return {"value": await self._get_all_paged_items(endpoint)}
            else:
                raise

    async def get_my_member_group_ids(self) -> list[str]:
        """Get IDs of Microsoft 365 groups the current user belongs to."""
        endpoint = "v1.0/me/memberOf/microsoft.graph.group?$select=id"
        try:
            groups = await self._get_all_paged_items(endpoint)
            return [cast(str, g.get("id")) for g in groups if g.get("id")]
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while listing memberOf groups, refreshing..."
                )
                await self.refresh_token()
                groups = await self._get_all_paged_items(endpoint)
                return [cast(str, g.get("id")) for g in groups if g.get("id")]
            raise

    async def get_group_root_sites_batched(
        self, group_ids: Sequence[str]
    ) -> dict[str, dict[str, str]]:
        """Resolve root sites for many groups via Graph $batch (20 GETs per POST).

        Returns group_id -> {"id": site_id, "webUrl": web_url}. Groups whose root
        site is inaccessible (403/404) are omitted. Sub-requests throttled inside
        the batch envelope are retried for up to BATCH_MAX_RETRY_ROUNDS extra
        rounds, honoring the largest inner Retry-After; anything still throttled
        after that is dropped, so the result may be partial.
        """
        results: dict[str, dict[str, str]] = {}
        pending = list(dict.fromkeys(gid for gid in group_ids if gid))
        semaphore = asyncio.Semaphore(self.BATCH_CONCURRENCY)

        async def post_batch(chunk: list[str]) -> dict[str, Any]:
            body = {
                "requests": [
                    {
                        "id": gid,
                        "method": "GET",
                        "url": f"/groups/{gid}/sites/root?$select=id,webUrl",
                    }
                    for gid in chunk
                ]
            }
            async with semaphore:
                try:
                    return await self.client.post(
                        "v1.0/$batch",
                        data=body,
                        headers=self.headers,
                        retryable_status_codes=TRANSIENT_STATUS_CODES,
                        retry_transport_errors=True,
                    )
                except aiohttp.ClientResponseError as e:
                    if e.status == 401 and self.can_refresh_token:
                        logger.info(
                            "SharePoint token expired during $batch, refreshing..."
                        )
                        await self.refresh_token()
                        return await self.client.post(
                            "v1.0/$batch",
                            data=body,
                            headers=self.headers,
                            retryable_status_codes=TRANSIENT_STATUS_CODES,
                            retry_transport_errors=True,
                        )
                    raise

        for round_index in range(self.BATCH_MAX_RETRY_ROUNDS + 1):
            if not pending:
                break

            chunks = [
                pending[i : i + self.BATCH_SIZE]
                for i in range(0, len(pending), self.BATCH_SIZE)
            ]
            envelopes = await asyncio.gather(*(post_batch(c) for c in chunks))

            retry_ids: list[str] = []
            max_retry_after = 0.0
            for envelope in envelopes:
                sub_responses = cast(
                    list[dict[str, Any]], envelope.get("responses") or []
                )
                for sub in sub_responses:
                    gid = sub.get("id")
                    status = sub.get("status")
                    if not isinstance(gid, str) or not gid:
                        continue
                    if status == 200:
                        body: dict[str, Any] = sub.get("body") or {}
                        site_id = body.get("id")
                        web_url = body.get("webUrl")
                        if isinstance(site_id, str) and site_id:
                            results[gid] = {
                                "id": site_id,
                                "webUrl": web_url if isinstance(web_url, str) else "",
                            }
                    elif status in (403, 404):
                        # Not all groups have an accessible site; non-fatal.
                        logger.debug(
                            "Could not fetch group root site in batch",
                            extra={"group_id": gid, "status": status},
                        )
                    elif status in THROTTLE_AND_OVERLOAD_STATUS_CODES:
                        retry_ids.append(gid)
                        raw_headers: dict[str, Any] = sub.get("headers") or {}
                        headers = {
                            str(k).lower(): str(v) for k, v in raw_headers.items()
                        }
                        retry_after = parse_retry_after(headers.get("retry-after"))
                        if retry_after is not None:
                            max_retry_after = max(max_retry_after, retry_after)
                    else:
                        logger.warning(
                            "Unexpected status in group root site batch",
                            extra={"group_id": gid, "status": status},
                        )

            pending = retry_ids
            if pending and round_index < self.BATCH_MAX_RETRY_ROUNDS:
                await asyncio.sleep(
                    min(
                        max(max_retry_after, self.BATCH_MIN_RETRY_SLEEP_SECONDS),
                        self.BATCH_MAX_RETRY_SLEEP_SECONDS,
                    )
                )

        if pending:
            logger.warning(
                "Gave up on %d throttled group root site lookups after %d retry rounds",
                len(pending),
                self.BATCH_MAX_RETRY_ROUNDS,
            )

        return results

    async def get_my_drive(self) -> dict[str, Any]:
        """Get current user's OneDrive drive info (requires delegated auth)."""
        try:
            return await self.client.get("v1.0/me/drive", headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info("Token expired while getting OneDrive, refreshing...")
                await self.refresh_token()
                return await self.client.get("v1.0/me/drive", headers=self.headers)
            else:
                raise

    async def get_drive_root_children(self, drive_id: str) -> list[SharePointItem]:
        """Get all items in root of a drive (works for both OneDrive and SharePoint)."""
        endpoint = f"v1.0/drives/{drive_id}/root/children"
        try:
            return await self._get_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info("Token expired while getting drive root, refreshing...")
                await self.refresh_token()
                return await self._get_items(endpoint)
            else:
                raise

    async def get_drive_folder_items(
        self, drive_id: str, folder_id: str
    ) -> list[SharePointItem]:
        """Get all items in a folder by drive_id (no site_id needed)."""
        endpoint = f"v1.0/drives/{drive_id}/items/{folder_id}/children"
        try:
            return await self._get_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info("Token expired while getting folder items, refreshing...")
                await self.refresh_token()
                return await self._get_items(endpoint)
            else:
                raise

    async def get_site_pages(self, site_id: str) -> dict[str, list[SharePointItem]]:
        endpoint = f"v1.0/sites/{site_id}/pages"
        try:
            return {"value": await self._get_all_paged_items(endpoint)}

        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                await self.refresh_token()
                return {"value": await self._get_all_paged_items(endpoint)}
            else:
                logger.error(f"SharePoint API error when getting page content: {e}")
                raise

    async def get_default_drive_id(self, site_id: str) -> Optional[str]:
        """Returnerar default drive-id för sajten (språk-agnostiskt)."""
        endpoint = f"v1.0/sites/{site_id}/drive"
        try:
            resp = cast(
                dict[str, Any], await self.client.get(endpoint, headers=self.headers)
            )
            # resp är redan JSON om BaseClient.get() dekodar; annars: resp = await resp.json()
            return cast(Optional[str], resp.get("id"))
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                await self.refresh_token()
                resp = cast(
                    dict[str, Any],
                    await self.client.get(endpoint, headers=self.headers),
                )
                return cast(Optional[str], resp.get("id"))
            raise

    async def get_drives(
        self, site_id: str, drive_name: Optional[str] = None
    ) -> Optional[str]:
        """Returnerar drive-id. Om drive_name är None, välj default documentLibrary deterministiskt."""
        endpoint = f"v1.0/sites/{site_id}/drives"
        try:
            response = cast(
                dict[str, Any], await self.client.get(endpoint, headers=self.headers)
            )
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired when listing drives, refreshing..."
                )
                await self.refresh_token()
                response = await self.client.get(endpoint, headers=self.headers)
            else:
                logger.error(f"Error listing drives: {e}")
                raise

        drives = cast(list[dict[str, Any]], response.get("value", []))
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

    async def get_file_metadata(self, drive_id: str, item_id: str) -> dict[str, Any]:
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
            return await self._get_item(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while getting file metadata, refreshing..."
                )
                await self.refresh_token()

                endpoint = f"v1.0/drives/{drive_id}/items/{item_id}"
                return await self._get_item(endpoint)
            else:
                logger.error(f"SharePoint API error when getting file metadata: {e}")
                raise

    async def get_item_metadata_batch(
        self, drive_id: str, item_ids: Sequence[str]
    ) -> dict[str, SharePointItemLookup]:
        """Read up to 20 items in one round trip, preserving each HTTP status.

        Only this narrow projection is needed to verify existence and scope.
        Missing, duplicate or malformed answers fail the batch: absence from a
        response is not evidence that an item was deleted. Inner throttling is
        returned to the caller, which can stop its bounded reconciliation pass.
        """
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return {}
        if len(ids) > self.BATCH_SIZE:
            raise ValueError("A Graph metadata batch supports at most 20 items")
        requests = [
            {
                "id": str(index),
                "method": "GET",
                "url": f"/drives/{quote(drive_id, safe='')}/items/"
                f"{quote(item_id, safe='')}?$select=id,name,parentReference",
            }
            for index, item_id in enumerate(ids)
        ]
        for attempt in range(2):
            try:
                envelope = cast(
                    dict[str, object],
                    await self.client.post(
                        "v1.0/$batch",
                        data={"requests": requests},
                        headers=self.headers,
                        retryable_status_codes=TRANSIENT_STATUS_CODES,
                        retry_transport_errors=True,
                    ),
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status == 401 and attempt == 0 and self.can_refresh_token:
                    await self.refresh_token()
                    continue
                raise
            responses = envelope.get("responses")
            if not isinstance(responses, list):
                raise ValueError("Graph metadata batch has no responses")
            expected = {str(index): item_id for index, item_id in enumerate(ids)}
            results: dict[str, SharePointItemLookup] = {}
            for raw in cast(list[object], responses):
                if not isinstance(raw, dict):
                    raise ValueError("Invalid Graph metadata response")
                response = cast(dict[str, object], raw)
                response_id = response.get("id")
                status = response.get("status")
                if not isinstance(response_id, str) or response_id not in expected:
                    raise ValueError("Unknown Graph metadata response id")
                item_id = expected[response_id]
                if item_id in results or type(status) is not int:
                    raise ValueError("Duplicate or invalid Graph metadata response")
                item: SharePointItem | None = None
                if status == 200:
                    body = response.get("body")
                    if not isinstance(body, dict):
                        raise ValueError("Graph metadata response has no item")
                    body_fields = cast(dict[str, object], body)
                    if body_fields.get("id") != item_id:
                        raise ValueError(
                            "Graph metadata response does not match the item"
                        )
                    item = cast(SharePointItem, body_fields)
                results[item_id] = SharePointItemLookup(status=status, item=item)
            if len(results) != len(ids):
                raise ValueError("Incomplete Graph metadata batch")
            if (
                attempt == 0
                and self.can_refresh_token
                and any(result.status == 401 for result in results.values())
            ):
                await self.refresh_token()
                continue
            return results
        raise RuntimeError("Graph metadata batch could not authenticate")

    async def get_folder_items(
        self,
        site_id: str,
        drive_id: str,
        folder_id: str,
    ) -> list[SharePointItem]:
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
            return await self._get_items(endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while getting folder items, refreshing..."
                )
                await self.refresh_token()
                endpoint = (
                    f"v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children"
                )
                return await self._get_items(endpoint)
            else:
                logger.error(f"SharePoint API error while getting folder items: {e}")
                raise

    async def get_page_content(self, site_id: str, page_id: str) -> dict[str, Any]:
        endpoint = f"v1.0/sites/{site_id}/pages/{page_id}/microsoft.graph.sitePage?$expand=canvasLayout"
        try:
            return await self.client.get(endpoint, headers=self.headers)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while getting page content, refreshing..."
                )
                await self.refresh_token()
                return await self.client.get(endpoint, headers=self.headers)
            logger.error(f"SharePoint API error when getting page content: {e}")
            raise

    async def get_file_extraction_by_id(
        self, drive_id: str, item_id: str
    ) -> ExtractionResult:
        """Download a file and extract its text.

        Returns a result rather than raising for anything that happens after
        the HTTP exchange, so callers can tell "no text" from "failed".
        """
        try:
            return await self._download_by_id(drive_id, item_id)
        except aiohttp.ClientResponseError as e:
            if e.status == 401 and self.can_refresh_token:
                logger.info(
                    "SharePoint token expired while getting file content, refreshing..."
                )
                await self.refresh_token()
                return await self._download_by_id(
                    drive_id, item_id, after_token_refresh=True
                )
            logger.error(f"SharePoint API error when getting file content: {e}")
            raise

    async def _download_by_id(
        self, drive_id: str, item_id: str, *, after_token_refresh: bool = False
    ) -> ExtractionResult:
        file_info = await self.get_file_metadata(drive_id, item_id)
        file_name = file_info.get("name", "")

        download_url = file_info.get("@microsoft.graph.downloadUrl")
        if not download_url:
            suffix = " after token refresh" if after_token_refresh else ""
            raise MissingDownloadUrlError(
                f"No download URL available for file '{file_name}' "
                f"(item_id={item_id}){suffix}"
            )

        return await self._download_file_content(
            download_url=download_url,
            file_name=file_name,
        )

    async def _get_delta_page(self, link: str) -> dict[str, Any]:
        """One delta page; drops the list item expansion if Graph rejects it.

        Only the first page carries our own query string; later pages come
        from ``@odata.nextLink``, which Graph builds from the accepted options.
        Graph otherwise lists the parent chain of every changed item too; those
        folders carry no change of their own and, above a folder scope, would
        read as having left it.
        """
        headers = {**self.headers, **DELTA_REQUEST_HEADERS}
        try:
            return await self.client.get(link, headers=headers)
        except aiohttp.ClientResponseError as e:
            if self._disable_item_expand_after(e):
                stripped = _strip_query_param(link, "$expand")
                return await self.client.get(stripped, headers=headers)
            raise

    async def _final_delta_link(self, endpoint: str) -> Optional[str]:
        """Follow delta pages to the deltaLink, discarding what they list."""
        headers = {**self.headers, **DELTA_REQUEST_HEADERS}
        next_link: Optional[str] = endpoint
        while next_link:
            if next_link.startswith("http"):
                next_link = _relative_graph_link(next_link)
            response = await self.client.get(next_link, headers=headers)
            if "@odata.deltaLink" in response:
                return cast(str, response["@odata.deltaLink"])
            next_link = cast(Optional[str], response.get("@odata.nextLink"))
        return None

    async def initialize_delta_token(
        self, drive_id: str, *, _retried: bool = False
    ) -> Optional[str]:
        """A delta token for the drive as it is now; ``None`` without a deltaLink.

        ``token=latest`` has Graph answer with the deltaLink alone instead of
        listing every item of the drive first. A drive that rejects it (400)
        is listed the old way.
        """
        delta_root = f"v1.0/drives/{drive_id}/root/delta"
        try:
            try:
                delta_link = await self._final_delta_link(f"{delta_root}?token=latest")
            except aiohttp.ClientResponseError as e:
                if e.status != 400:
                    raise
                logger.warning(
                    "Graph rejected token=latest for drive %s; listing the drive "
                    "for a delta baseline",
                    drive_id,
                )
                delta_link = await self._final_delta_link(delta_root)

            if not delta_link:
                logger.warning(f"No deltaLink found for drive {drive_id}")
                return None

            token = _token_from_delta_link(delta_link)

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
            elif e.status == 401 and self.can_refresh_token and not _retried:
                logger.info("SharePoint token expired during delta init, refreshing...")
                await self.refresh_token()
                return await self.initialize_delta_token(drive_id, _retried=True)
            else:
                logger.error(f"Error initializing delta token: {e}")
                raise

    async def get_delta_changes(
        self, drive_id: str, delta_token: str, *, _retried: bool = False
    ) -> tuple[list[SharePointItem], Optional[str]]:
        """
        Get changes since the last delta sync using the stored token.

        Args:
            drive_id: The drive ID
            delta_token: The token from the previous sync

        Returns:
            Tuple of (list of changed items, new delta token for next sync)
        """
        try:
            endpoint = self._with_item_expand(
                f"v1.0/drives/{drive_id}/root/delta?token={quote(delta_token, safe='')}"
            )

            all_changes: list[SharePointItem] = []
            next_link = endpoint
            new_delta_token = None

            while next_link:
                # Handle full URL or relative endpoint
                if next_link.startswith("http"):
                    next_link = _relative_graph_link(next_link)

                response = await self._get_delta_page(next_link)

                # Collect changed items
                items = response.get("value", [])
                all_changes.extend(items)

                # Check for next page
                next_link = cast(str | None, response.get("@odata.nextLink"))

                # Check for new delta token
                if "@odata.deltaLink" in response:
                    new_delta_token = _token_from_delta_link(
                        cast(str, response["@odata.deltaLink"])
                    )
                    break

            if not new_delta_token:
                logger.warning(f"No new delta token received for drive {drive_id}")
                # Return the old token so we don't lose sync state
                new_delta_token = delta_token

            logger.info(f"Retrieved {len(all_changes)} changes for drive {drive_id}")
            latest: dict[str, SharePointItem] = {}
            without_id: list[SharePointItem] = []
            for item in all_changes:
                item_id = item.get("id")
                if item_id:
                    latest[item_id] = item
                else:
                    without_id.append(item)
            return [*latest.values(), *without_id], new_delta_token

        except aiohttp.ClientResponseError as e:
            if e.status == 410:
                raise DeltaTokenExpiredException(
                    f"Delta token expired (410 Gone) for drive {drive_id}"
                ) from e
            elif e.status == 401 and self.can_refresh_token and not _retried:
                logger.info(
                    "SharePoint token expired during delta query, refreshing..."
                )
                await self.refresh_token()
                return await self.get_delta_changes(
                    drive_id, delta_token, _retried=True
                )
            else:
                logger.error(f"Error getting delta changes: {e}")
                raise
