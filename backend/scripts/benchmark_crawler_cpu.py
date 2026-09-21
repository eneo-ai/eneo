"""Compare event-loop responsiveness on identical HTML/chunking workloads.

Run each case in a fresh process, e.g.:
uv run python scripts/benchmark_crawler_cpu.py --mode inline --links 10000 --jobs 4
uv run python scripts/benchmark_crawler_cpu.py --mode offload --links 10000 --jobs 4
"""

import argparse
import asyncio
import json
import resource
import sys
import time

from langchain_text_splitters import RecursiveCharacterTextSplitter

from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.crawler.extraction import extract_html


async def benchmark(mode: str, links: int, jobs: int):
    html = (
        "<html><main><h1>Public information</h1>"
        + "".join(
            f'<p>Information about municipal services {i}. <a href="/page/{i}">Read more</a></p>'
            for i in range(links)
        )
        + "</main></html>"
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=200, chunk_overlap=40, length_function=count_tokens
    )
    count_tokens("Warm the tokenizer before measuring")
    lag = []
    finished = False

    async def ticker():
        while not finished:
            before = time.perf_counter()
            await asyncio.sleep(0.01)
            lag.append(max(0, time.perf_counter() - before - 0.01))

    async def work():
        if mode == "inline":
            page = extract_html(html, "https://example.test/")
            chunks = splitter.split_text(page.content)
        else:
            from eneo.crawler.cpu_work import run_cpu_work

            page = await run_cpu_work(extract_html, html, "https://example.test/")
            chunks = await run_cpu_work(splitter.split_text, page.content)
        return len(page.links), len(chunks)

    heartbeat = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    cpu_start = time.process_time()
    started = time.perf_counter()
    counts = await asyncio.gather(*(work() for _ in range(jobs)))
    elapsed = time.perf_counter() - started
    cpu = time.process_time() - cpu_start
    finished = True
    await heartbeat
    print(
        json.dumps(
            {
                "mode": mode,
                "links": links,
                "html_bytes": len(html.encode()),
                "jobs": jobs,
                "elapsed_seconds": round(elapsed, 3),
                "cpu_seconds": round(cpu, 3),
                "max_loop_lag_ms": round(max(lag, default=0) * 1000, 1),
                "p95_loop_lag_ms": round(
                    sorted(lag)[int((len(lag) - 1) * 0.95)] * 1000, 1
                ),
                "peak_rss_mib": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    / (1024**2 if sys.platform == "darwin" else 1024),
                    1,
                ),
                "counts": counts,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inline", "offload"), required=True)
    parser.add_argument("--links", type=int, default=10000)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(benchmark(args.mode, args.links, args.jobs))
