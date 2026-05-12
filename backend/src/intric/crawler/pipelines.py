import hashlib
import re
from email.message import Message
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import unquote, urlparse

import scrapy
import scrapy.http
from scrapy import signals as scrapy_signals
from scrapy.exceptions import StopDownload
from scrapy.pipelines.files import FilesPipeline
from twisted.internet.defer import CancelledError
from twisted.python.failure import Failure
from typing_extensions import override

# Maximum filename length in bytes (ext4 limit is 255, leave room for safety)
MAX_FILENAME_BYTES = 200
FILE_STATUS_TOO_LARGE = "too_large"
FILE_TOO_LARGE_SKIPPED_STAT = "file_too_large_skipped_count"
INTRIC_FILE_DOWNLOAD_META_KEY = "intric_file_download"
FILE_SIZE_SKIP_RECORDED_META_KEY = "intric_file_size_skip_recorded"
FILE_SIZE_SKIP_OBSERVED_BYTES_META_KEY = "intric_file_size_skip_observed_bytes"


def _truncate_filename(filename: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    """Truncate filename if it exceeds filesystem limits while preserving extension.

    Security: Sanitizes directory separators to prevent path traversal.
    Performance: O(N) byte slicing instead of O(N²) character iteration.

    When truncating, adds a short hash to maintain uniqueness for files
    that would otherwise have the same truncated name.
    """
    if not filename:
        return "unnamed_file"

    # 1. Decode URL-encoding
    decoded = unquote(filename)

    # 2. SECURITY: Remove directory separators and null bytes
    # Prevents path traversal attacks like %2Fetc%2Fpasswd -> /etc/passwd
    clean_name = re.sub(r"[/\\]", "_", decoded).replace("\0", "")

    # 3. Check length early (most filenames will exit here)
    encoded_name = clean_name.encode("utf-8")
    if len(encoded_name) <= max_bytes:
        return clean_name

    # 4. Split stem and extension
    path_obj = PurePosixPath(clean_name)
    suffix = path_obj.suffix  # e.g., ".pdf"
    stem = path_obj.stem  # filename without extension

    # 5. Handle Edge Case: Extension too long
    # Reserve 40 bytes for hash+separators, leave rest for extension
    encoded_suffix = suffix.encode("utf-8")
    if len(encoded_suffix) > (max_bytes - 40):
        suffix = encoded_suffix[: (max_bytes - 40)].decode("utf-8", "ignore")
        encoded_suffix = suffix.encode("utf-8")

    # 6. Calculate available space for stem
    # Structure: {stem}_{hash}{suffix}
    hash_suffix = hashlib.md5(encoded_name).hexdigest()[:8]
    reserved_bytes = 1 + 8 + len(encoded_suffix)  # "_" + hash + suffix
    available_for_stem = max_bytes - reserved_bytes

    if available_for_stem < 1:
        # Fallback if no room for stem (shouldn't happen with reasonable extensions)
        return f"file_{hash_suffix}{suffix}"

    # 7. PERFORMANCE: O(N) byte slicing instead of O(N²) char iteration
    # This safely handles multi-byte characters by decoding with 'ignore'
    encoded_stem = stem.encode("utf-8")
    truncated_stem = encoded_stem[:available_for_stem].decode("utf-8", "ignore")

    return f"{truncated_stem}_{hash_suffix}{suffix}"


class FileNamePipeline(FilesPipeline):
    def get_media_requests(self, item: object, info: object) -> list[scrapy.Request]:
        requests = list(super().get_media_requests(item, info))
        for request in requests:
            _request_meta(request)[INTRIC_FILE_DOWNLOAD_META_KEY] = True
        return requests

    def media_failed(
        self,
        failure: Failure,
        request: object,
        info: object,
    ) -> dict[str, object] | None:
        if _is_file_download_too_large_failure(failure):
            _record_file_too_large_skip(
                spider=cast(Any, info).spider,
                request=request,
                observed_size=_observed_size_from_request(request),
            )
            return {
                "url": _request_url(request),
                "path": None,
                "checksum": None,
                "status": FILE_STATUS_TOO_LARGE,
            }

        return super().media_failed(failure, request, info)

    @override
    def file_path(
        self,
        request: scrapy.Request,
        response: scrapy.http.Response | None = None,
        info: object = None,
        *,
        item: object = None,
    ) -> str:
        filename = None

        if response is not None:
            cd_raw = response.headers.get(b"Content-Disposition")
            if cd_raw:
                msg = Message()
                # Decode header bytes safely to handle non-ASCII headers
                msg["content-disposition"] = cd_raw.decode("utf-8", "ignore")
                filename = msg.get_filename()

        if not filename:
            # Fallback to URL path; cast request.url to str (Scrapy URL type is untyped)
            filename = PurePosixPath(urlparse(str(request.url)).path).name

        if not filename:
            url_hash = hashlib.md5(request.url.encode("utf-8")).hexdigest()[:8]
            filename = f"unnamed_{url_hash}"

        return _truncate_filename(filename)


class FileSizeLimitStatsExtension:
    def __init__(self, download_max_size: int):
        self._download_max_size = download_max_size

    @classmethod
    def from_crawler(cls, crawler: object) -> "FileSizeLimitStatsExtension":
        scrapy_crawler = cast(Any, crawler)
        extension = cls(
            download_max_size=cast(
                int,
                scrapy_crawler.settings.getint("DOWNLOAD_MAXSIZE"),
            )
        )
        scrapy_crawler.signals.connect(
            extension.headers_received,
            signal=scrapy_signals.headers_received,
        )
        scrapy_crawler.signals.connect(
            extension.bytes_received,
            signal=scrapy_signals.bytes_received,
        )
        return extension

    def headers_received(
        self,
        headers: object,
        body_length: int,
        request: object,
        spider: object,
    ) -> None:
        del headers
        if not self._should_stop_file_download(request, observed_size=body_length):
            return

        _record_file_too_large_skip(
            spider=spider,
            request=request,
            observed_size=body_length,
        )
        raise _new_stop_download()

    def bytes_received(self, data: bytes, request: object, spider: object) -> None:
        observed_size = _observed_size_from_request(request) + len(data)
        _request_meta(request)[FILE_SIZE_SKIP_OBSERVED_BYTES_META_KEY] = observed_size
        if not self._should_stop_file_download(request, observed_size=observed_size):
            return

        _record_file_too_large_skip(
            spider=spider,
            request=request,
            observed_size=observed_size,
        )
        raise _new_stop_download()

    def _should_stop_file_download(
        self,
        request: object,
        *,
        observed_size: int,
    ) -> bool:
        meta = _request_meta(request)
        return (
            self._download_max_size > 0
            and observed_size > self._download_max_size
            and meta.get(INTRIC_FILE_DOWNLOAD_META_KEY) is True
            and meta.get(FILE_SIZE_SKIP_RECORDED_META_KEY) is not True
        )


def _is_file_download_too_large_failure(failure: Failure) -> bool:
    failure_value = getattr(failure, "value", None)
    if isinstance(failure_value, StopDownload):
        return True

    if not isinstance(failure_value, CancelledError):
        return False

    message = str(failure_value).lower()
    return "larger than download max size" in message


def _observed_size_from_request(request: object) -> int:
    observed_size = _request_meta(request).get(FILE_SIZE_SKIP_OBSERVED_BYTES_META_KEY)
    return observed_size if isinstance(observed_size, int) else 0


def _record_file_too_large_skip(
    *,
    spider: object,
    request: object,
    observed_size: int,
) -> None:
    meta = _request_meta(request)
    if meta.get(FILE_SIZE_SKIP_RECORDED_META_KEY) is True:
        return

    meta[FILE_SIZE_SKIP_RECORDED_META_KEY] = True
    stats = cast(Any, spider).crawler.stats
    stats.inc_value(FILE_TOO_LARGE_SKIPPED_STAT, spider=spider)
    stats.inc_value(f"file_status_count/{FILE_STATUS_TOO_LARGE}", spider=spider)
    stats.max_value(
        "file_too_large_skipped/max_observed_size_bytes",
        observed_size,
        spider=spider,
    )


def _request_meta(request: object) -> dict[str, object]:
    meta = getattr(request, "meta", None)
    assert isinstance(meta, dict)
    return cast(dict[str, object], meta)


def _request_url(request: object) -> str:
    return str(getattr(request, "url", ""))


def _new_stop_download() -> BaseException:
    return StopDownload(fail=True)
