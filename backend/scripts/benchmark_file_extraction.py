"""Measure repeated file extraction and resource recovery on Linux.

uv run python scripts/benchmark_file_extraction.py
Uses generated documents and private temporary files, with no provider calls.
"""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from eneo.files.extraction_limits import FileExtractionLimits
from eneo.files.text import ExtractionLimitError, TextExtractor


def rss_kib(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except FileNotFoundError:
        pass
    return 0


async def benchmark():
    extractor = TextExtractor()
    with TemporaryDirectory(prefix="eneo-extraction-benchmark-") as directory:
        root = Path(directory)
        text = (
            "Municipal services: applications, opening hours and contact information.\n"
            * 1000
        )
        txt = root / "services.txt"
        txt.write_text(text)
        document = Document()
        for line in text.splitlines():
            document.add_paragraph(line)
        docx = root / "services.docx"
        document.save(str(docx))
        await extractor.extract_bounded(txt)
        baseline_fds = len(list(Path("/proc/self/fd").iterdir()))
        baseline_rss = rss_kib(os.getpid())
        processes = []
        original_spawn = asyncio.create_subprocess_exec

        async def record_spawn(*args, **kwargs):
            process = await original_spawn(*args, **kwargs)
            processes.append(process)
            return process

        asyncio.create_subprocess_exec = record_spawn
        peak_child_rss = 0
        finished = False

        async def sample():
            nonlocal peak_child_rss
            while not finished:
                peak_child_rss = max(
                    peak_child_rss,
                    *(rss_kib(p.pid) for p in processes if p.returncode is None),
                    0,
                )
                await asyncio.sleep(0.01)

        monitor = asyncio.create_task(sample())
        files = []
        try:
            for path in (txt, docx):
                started = time.perf_counter()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                hash_ms = (time.perf_counter() - started) * 1000
                times = []
                extracted_hashes = []
                for _ in range(3):
                    started = time.perf_counter()
                    extracted = await extractor.extract_bounded(path)
                    times.append(round(time.perf_counter() - started, 3))
                    extracted_hashes.append(
                        hashlib.sha256(extracted.encode()).hexdigest()
                    )
                assert len(set(extracted_hashes)) == 1
                files.append(
                    {
                        "format": path.suffix,
                        "bytes": path.stat().st_size,
                        "sha256": digest,
                        "hash_ms": round(hash_ms, 3),
                        "extraction_seconds": times,
                    }
                )
            fifo = root / "blocked.txt"
            os.mkfifo(fifo)
            for _ in range(3):
                try:
                    await extractor.extract_bounded(
                        fifo,
                        "text/plain",
                        limits=FileExtractionLimits(timeout_seconds=0.5),
                    )
                except ExtractionLimitError:
                    pass
                else:
                    raise AssertionError("Blocked extraction did not time out")
                task = asyncio.create_task(
                    extractor.extract_bounded(fifo, "text/plain")
                )
                await asyncio.sleep(0.25)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            assert all(process.returncode is not None for process in processes)
        finally:
            finished = True
            await monitor
            asyncio.create_subprocess_exec = original_spawn
        print(
            json.dumps(
                {
                    "files": files,
                    "timeout_cycles": 3,
                    "cancellation_cycles": 3,
                    "children_reaped": len(processes),
                    "child_peak_rss_mib": round(peak_child_rss / 1024, 1),
                    "parent_rss_before_mib": round(baseline_rss / 1024, 1),
                    "parent_rss_after_mib": round(rss_kib(os.getpid()) / 1024, 1),
                    "parent_fds_before": baseline_fds,
                    "parent_fds_after": len(list(Path("/proc/self/fd").iterdir())),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(benchmark())
