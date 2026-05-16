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

from intric.websites.domain.crawl_run import (
    MAX_CRAWL_FILE_TOO_LARGE_SAMPLES,
    truncate_crawl_file_too_large_sample_url,
)

# Maximum filename length in bytes (ext4 limit is 255, leave room for safety)
MAX_FILENAME_BYTES = 200
FILE_STATUS_TOO_LARGE = "too_large"
FILE_TOO_LARGE_SKIPPED_STAT = "file_too_large_skipped_count"
FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT = "file_too_large_skipped/samples"
FILE_TOO_LARGE_DOWNLOAD_LIMIT_STAT = "file_too_large_skipped/download_limit_bytes"
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
                observed_size=_observed_size_from_request(request)
                or _observed_size_from_failure(failure),
                download_max_size=_download_max_size_from_spider(
                    cast(Any, info).spider
                ),
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
        body_length: object,
        request: object,
        spider: object,
    ) -> None:
        """Scrapy passes `body_length` as `object` despite its docstring saying
        `int`: on real-world HTTP responses Content-Length may surface as a
        decimal `str`, bytes, or be missing entirely (HTTP/1.1 chunked
        encoding, HTTP/2 trailers). Coerce defensively at the signal boundary
        so the `_should_stop_file_download` comparison never sees a non-int —
        the previous annotation `body_length: int` was a load-bearing fiction
        that raised `TypeError: '>' not supported between instances of 'str'
        and 'int'` on the hot path. When the header is unparseable the early
        size check is skipped and `bytes_received` still bounds the download.
        """
        del headers
        observed = _coerce_optional_nonnegative_int(body_length)
        if observed is None:
            return
        if not self._should_stop_file_download(request, observed_size=observed):
            return

        _record_file_too_large_skip(
            spider=spider,
            request=request,
            observed_size=observed,
            download_max_size=self._download_max_size,
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
            download_max_size=self._download_max_size,
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


def _coerce_optional_nonnegative_int(value: object) -> int | None:
    """Coerce a Scrapy-signal-supplied size value to a non-negative int.

    Scrapy's `headers_received` signal documents `body_length: int` but in
    practice forwards the raw Content-Length header value, which arrives as
    `str` (`"1024"`), `bytes` (`b"1024"`), `int` (parsed by some middleware),
    or is absent entirely (chunked transfer / HTTP/2 trailers). Returns
    `None` for any value that cannot be safely interpreted as a non-negative
    int so the caller can skip the early size check and rely on the
    cumulative `bytes_received` path instead.
    """
    if isinstance(value, bool):
        return None  # bool is an int subclass; reject explicitly to avoid surprises
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _observed_size_from_failure(failure: Failure) -> int:
    failure_value = getattr(failure, "value", None)
    # Scrapy's HTTP/1.1 handler currently includes the observed byte count in
    # CancelledError messages when DOWNLOAD_MAXSIZE stops a response mid-body.
    match = re.search(r"\((\d+)\).*larger than download max size", str(failure_value))
    if match is None:
        return 0
    return int(match.group(1))


def _download_max_size_from_spider(spider: object) -> int | None:
    settings = getattr(getattr(spider, "crawler", None), "settings", None)
    getint = getattr(settings, "getint", None)
    if not callable(getint):
        return None
    value = getint("DOWNLOAD_MAXSIZE")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _record_file_too_large_skip(
    *,
    spider: object,
    request: object,
    observed_size: int,
    download_max_size: int | None,
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
    if download_max_size is not None:
        stats.set_value(FILE_TOO_LARGE_DOWNLOAD_LIMIT_STAT, download_max_size)
    _append_file_too_large_sample(
        stats=stats,
        url=_request_url(request),
        observed_size=observed_size,
    )


def _append_file_too_large_sample(
    *,
    stats: object,
    url: str,
    observed_size: int,
) -> None:
    stats_owner = cast(Any, stats)
    raw_samples = stats_owner.get_value(FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT, [])
    samples: list[object] = (
        cast(list[object], raw_samples) if isinstance(raw_samples, list) else []
    )
    if len(samples) >= MAX_CRAWL_FILE_TOO_LARGE_SAMPLES:
        return
    sample = {
        "url": truncate_crawl_file_too_large_sample_url(url),
        "observed_size_bytes": observed_size if observed_size > 0 else None,
    }
    stats_owner.set_value(FILE_TOO_LARGE_SKIPPED_SAMPLES_STAT, [*samples, sample])


def _request_meta(request: object) -> dict[str, object]:
    meta = getattr(request, "meta", None)
    assert isinstance(meta, dict)
    return cast(dict[str, object], meta)


def _request_url(request: object) -> str:
    return str(getattr(request, "url", ""))


def _new_stop_download() -> BaseException:
    return StopDownload(fail=True)
