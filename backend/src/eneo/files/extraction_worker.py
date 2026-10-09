"""One disposable document parser. Keep imports before limits to the stdlib."""

import ctypes
import os
import resource
import signal
import sys
import zipfile
from enum import IntEnum
from pathlib import Path


class ExtractionExit(IntEnum):
    SUCCESS = 0
    FAILED = 2
    LIMIT = 3
    ENCRYPTED = 4
    CORRUPT = 5
    UNSUPPORTED = 6


def configure_process_limits(
    parent_pid: int, cpu_seconds: int, memory_bytes: int
) -> None:
    if sys.platform == "linux":
        # Kill an extractor if its worker dies before it can run cleanup. The
        # parent check closes the race between exec and PR_SET_PDEATHSIG.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Unable to set extractor parent signal")
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGKILL)
        # Address space is an enforceable allocation ceiling, not an RSS metric.
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> int:
    parent_pid, cpu_seconds, memory_bytes = map(int, sys.argv[1:4])
    configure_process_limits(parent_pid, cpu_seconds, memory_bytes)

    from eneo.files.extraction_limits import FileExtractionLimits
    from eneo.files.text import (
        CorruptFileError,
        EncryptedFileError,
        ExtractionLimitError,
        TextExtractor,
        UnsupportedFormatError,
    )

    limits = FileExtractionLimits.model_validate_json(sys.argv[4])
    filepath = Path(sys.argv[5])
    mimetype, filename = sys.argv[6:8]
    try:
        if zipfile.is_zipfile(filepath):
            with zipfile.ZipFile(filepath) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > limits.max_archive_entries
                    or sum(entry.file_size for entry in entries)
                    > limits.max_archive_bytes
                ):
                    return ExtractionExit.LIMIT
        text = TextExtractor().extract(
            filepath, mimetype or None, filename, limits=limits
        )
        if len(text) > limits.max_output_bytes:
            return ExtractionExit.LIMIT
        encoded = text.encode("utf-8")
        if len(encoded) > limits.max_output_bytes:
            return ExtractionExit.LIMIT
        sys.stdout.buffer.write(encoded)
        return ExtractionExit.SUCCESS
    except (MemoryError, ExtractionLimitError):
        return ExtractionExit.LIMIT
    except EncryptedFileError:
        return ExtractionExit.ENCRYPTED
    except (CorruptFileError, zipfile.BadZipFile):
        return ExtractionExit.CORRUPT
    except UnsupportedFormatError:
        return ExtractionExit.UNSUPPORTED
    except Exception:
        return ExtractionExit.FAILED


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MemoryError:
        sys.exit(ExtractionExit.LIMIT)
