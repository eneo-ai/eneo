import hashlib
import re
from email.message import Message
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import scrapy
import scrapy.http
from scrapy.pipelines.files import FilesPipeline

# Maximum filename length in bytes (ext4 limit is 255, leave room for safety)
MAX_FILENAME_BYTES = 200


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
    def file_path(
        self,
        request: scrapy.Request,
        response: scrapy.http.Response = None,
        info=None,
        *,
        item=None,
    ):
        filename = None

        if response is not None:
            cd_header = response.headers.get(b"Content-Disposition")
            if cd_header:
                msg = Message()
                # Decode header bytes safely to handle non-ASCII headers
                msg["content-disposition"] = cd_header.decode("utf-8", "ignore")
                filename = msg.get_filename()

        if not filename:
            # Fallback to URL path
            filename = PurePosixPath(urlparse(request.url).path).name

        if not filename:
            url_hash = hashlib.md5(request.url.encode("utf-8")).hexdigest()[:8]
            filename = f"unnamed_{url_hash}"

        return _truncate_filename(filename)
