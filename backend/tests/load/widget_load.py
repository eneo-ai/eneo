# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Load test for the public widget surface.

Simulates many anonymous visitors hitting one active widget at once and
reports how the limits behave: every visitor solves the ALTCHA challenge,
mints a token and asks a few questions. Answers are read to the end so the
budget is settled exactly as in production. The run is not a benchmark; it is
a check that

* nothing gets through without a token or a solved challenge,
* per-visitor and per-IP rate limits and the daily token budget produce 429s
  with a Retry-After instead of letting traffic through, and
* losing Redis fails closed (503) instead of open.

Run it against the isolated E2E stack (deterministic mock model, no real
provider). From inside that stack's backend container:

    python tests/load/widget_load.py --base-url http://localhost:8000 \
        --public-id wgt_… --visitors 200 --messages 3

See docs/adr/embeddable-widgets/04-review.md for the recorded results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

import altcha
import httpx


@dataclass
class Report:
    statuses: Counter[str] = field(default_factory=Counter)
    codes: Counter[str] = field(default_factory=Counter)
    latencies_ms: list[float] = field(default_factory=list)
    retry_after_present: int = 0
    retry_after_missing: int = 0
    transport_errors: Counter[str] = field(default_factory=Counter)
    unauthenticated_asks_rejected: int = 0
    unauthenticated_asks_allowed: int = 0

    def note(self, response: httpx.Response, started: float) -> None:
        self.latencies_ms.append((time.perf_counter() - started) * 1000)
        self.statuses[str(response.status_code)] += 1
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
                code = detail.get("code") if isinstance(detail, dict) else str(detail)
            except Exception:
                code = "unparseable"
            self.codes[str(code)] += 1
            if response.status_code in (429, 503):
                if response.headers.get("retry-after"):
                    self.retry_after_present += 1
                else:
                    self.retry_after_missing += 1


async def _solve(client: httpx.AsyncClient, public_id: str) -> str:
    resp = await client.get(f"/api/v1/widgets/{public_id}/challenge/")
    resp.raise_for_status()
    challenge = altcha.Challenge.from_dict(resp.json())
    # Pure-Python SHA-256 loop: keep it off the event loop so the streams of
    # the other visitors are not starved.
    solution = await asyncio.to_thread(altcha.solve_challenge, challenge)
    if solution is None:
        raise ChallengeUnsolved()
    return altcha.Payload(challenge=challenge, solution=solution).to_base64()


class ChallengeUnsolved(Exception):
    """The solver gave up (expired or malformed challenge)."""


async def _visitor(
    client: httpx.AsyncClient,
    public_id: str,
    messages: int,
    report: Report,
    gate: asyncio.Semaphore,
) -> None:
    async with gate:
        try:
            await _visit(client, public_id, messages, report)
        except (httpx.HTTPError, ChallengeUnsolved) as exc:
            # A dropped connection or an unsolved challenge is a finding, not
            # a reason to abort the run.
            report.transport_errors[type(exc).__name__] += 1


async def _visit(
    client: httpx.AsyncClient, public_id: str, messages: int, report: Report
) -> None:
    if True:
        started = time.perf_counter()
        # Nothing without a token: must be rejected.
        bare = await client.post(
            f"/api/v1/widgets/{public_id}/ask/", json={"question": "hej"}
        )
        if bare.status_code == 401:
            report.unauthenticated_asks_rejected += 1
        else:
            report.unauthenticated_asks_allowed += 1

        try:
            altcha = await _solve(client, public_id)
        except httpx.HTTPStatusError as exc:
            report.note(exc.response, started)
            return
        resp = await client.post(
            f"/api/v1/widgets/{public_id}/visitor-sessions/",
            json={"altcha": altcha, "visitor_id": str(uuid4())},
        )
        report.note(resp, started)
        if resp.status_code != 200:
            return
        token = resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        session_id: Optional[str] = None
        for i in range(messages):
            started = time.perf_counter()
            async with client.stream(
                "POST",
                f"/api/v1/widgets/{public_id}/ask/",
                json={"question": f"Fråga {i + 1}", "session_id": session_id},
                headers=headers,
            ) as stream:
                if stream.status_code != 200:
                    await stream.aread()
                    report.note(stream, started)
                    break
                async for line in stream.aiter_lines():
                    if line.startswith("data:") and session_id is None:
                        try:
                            payload: dict[str, Any] = json.loads(line[5:])
                            session_id = payload.get("session_id") or session_id
                        except json.JSONDecodeError:
                            pass
                report.note(stream, started)


async def run(args: argparse.Namespace) -> Report:
    report = Report()
    gate = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency + 10)
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=httpx.Timeout(60.0), limits=limits
    ) as client:
        await asyncio.gather(
            *(
                _visitor(client, args.public_id, args.messages, report, gate)
                for _ in range(args.visitors)
            )
        )
    return report


def print_report(report: Report, args: argparse.Namespace) -> None:
    print(
        f"visitors={args.visitors} messages/visitor={args.messages} concurrency={args.concurrency}"
    )
    print("status codes:", dict(sorted(report.statuses.items())))
    print("error codes:", dict(sorted(report.codes.items())))
    print(
        "unauthenticated asks rejected/allowed:",
        report.unauthenticated_asks_rejected,
        "/",
        report.unauthenticated_asks_allowed,
    )
    print(
        "Retry-After on 429/503 present/missing:",
        report.retry_after_present,
        "/",
        report.retry_after_missing,
    )
    print("transport errors:", dict(report.transport_errors))
    if report.latencies_ms:
        sorted_latencies = sorted(report.latencies_ms)
        p95 = sorted_latencies[int(len(sorted_latencies) * 0.95) - 1]
        print(
            f"latency ms: median={statistics.median(sorted_latencies):.0f} "
            f"p95={p95:.0f} max={sorted_latencies[-1]:.0f}"
        )
    if report.unauthenticated_asks_allowed:
        raise SystemExit("FAIL: an ask without a visitor token was answered")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--public-id", required=True)
    parser.add_argument("--visitors", type=int, default=200)
    parser.add_argument("--messages", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print_report(report, args)


if __name__ == "__main__":
    main()
