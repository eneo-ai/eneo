import asyncio
import os
import signal
import sys
from pathlib import Path

from eneo.files.extraction_limits import (
    FileExtractionLimits,
    get_file_extraction_limits,
)
from eneo.files.extraction_worker import ExtractionExit
from eneo.files.text import (
    CorruptFileError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
    UnsupportedFormatError,
)

_process_slots: asyncio.Semaphore | None = None


async def _kill_and_reap(spawn: asyncio.Task[asyncio.subprocess.Process]) -> None:
    process = await spawn
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    # Drain the bounded pipe backlog after killing. Waiting without draining a
    # full stdout pipe can leave asyncio's process transport waiting forever.
    await process.communicate()


async def extract_in_process(
    filepath: Path,
    mimetype: str | None,
    filename: str,
    *,
    limits: FileExtractionLimits | None = None,
) -> str:
    global _process_slots
    configured = get_file_extraction_limits()
    limits = limits or configured
    if _process_slots is None:
        _process_slots = asyncio.Semaphore(configured.concurrency)

    async with _process_slots:
        # Keep numerical libraries from reserving one thread stack per CPU in
        # each child. The process boundary, rather than thread cancellation,
        # owns the lifetime of parser work and its open input descriptors.
        child_env = os.environ | {
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "eneo.files.extraction_worker",
                str(os.getpid()),
                str(limits.cpu_seconds),
                str(limits.memory_bytes),
                limits.model_dump_json(),
                str(filepath.resolve()),
                mimetype or "",
                filename,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=child_env,
            )
        )
        try:
            async with asyncio.timeout(limits.timeout_seconds):
                # Cancellation during launch must still recover the child
                # handle so cleanup can kill and reap it before releasing its slot.
                process = await asyncio.shield(spawn)
                assert process.stdout is not None
                output = bytearray()
                while block := await process.stdout.read(64 * 1024):
                    if len(output) + len(block) > limits.max_output_bytes:
                        raise ExtractionLimitError(filename, "text output limit")
                    output.extend(block)
                status = await process.wait()
                if status in (ExtractionExit.LIMIT, -signal.SIGKILL, -signal.SIGXCPU):
                    raise ExtractionLimitError(filename, "document resource limit")
                if status == ExtractionExit.ENCRYPTED:
                    raise EncryptedFileError(filename)
                if status == ExtractionExit.CORRUPT:
                    raise CorruptFileError(filename)
                if status == ExtractionExit.UNSUPPORTED:
                    raise UnsupportedFormatError(filename, mimetype or filepath.suffix)
                if status != ExtractionExit.SUCCESS:
                    raise ExtractionError(f"Extraction failed for '{filename}'")
                return output.decode("utf-8")
        except TimeoutError as error:
            raise ExtractionLimitError(filename, "extraction deadline") from error
        finally:
            # Shield the launch and reap even when the owning crawl or upload
            # is cancelled. No acknowledgement or input-file cleanup precedes this.
            reaped = asyncio.create_task(_kill_and_reap(spawn))
            cancelled = False
            while not reaped.done():
                try:
                    await asyncio.shield(reaped)
                except asyncio.CancelledError:
                    # A repeated cancellation must not release the concurrency
                    # slot while the operating system still owns the child.
                    cancelled = True
            reaped.result()
            if cancelled:
                raise asyncio.CancelledError
