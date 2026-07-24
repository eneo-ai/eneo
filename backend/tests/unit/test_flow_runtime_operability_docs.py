from __future__ import annotations

import re
from pathlib import Path

from eneo.flows.runtime.flow_runtime_health import FlowRuntimeHealthFlag

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FLOW_RUNBOOK = REPOSITORY_ROOT / "docs" / "runbooks" / "flows.md"
TROUBLESHOOTING = REPOSITORY_ROOT / "docs" / "TROUBLESHOOTING.md"


def _health_flag_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in FLOW_RUNBOOK.read_text().splitlines():
        match = re.fullmatch(r"\| `([A-Z_]+)` \| ([^|]+) \| ([^|]+) \|", line)
        if match:
            rows[match.group(1)] = (match.group(2).strip(), match.group(3).strip())
    return rows


def test_troubleshooting_links_to_flow_runtime_runbook() -> None:
    troubleshooting = TROUBLESHOOTING.read_text()

    assert "[Flow Runtime Runbook](runbooks/flows.md)" in troubleshooting


def test_runbook_maps_every_health_flag_to_threshold_and_recovery() -> None:
    rows = _health_flag_rows()

    assert set(rows) == {flag.value for flag in FlowRuntimeHealthFlag}
    assert all(threshold and recovery for threshold, recovery in rows.values())


def test_runbook_covers_auth_staleness_liveness_and_raw_export_controls() -> None:
    runbook = " ".join(FLOW_RUNBOOK.read_text().lower().split())

    assert "x-api-key" in runbook and "/api/healthz/flows" in runbook
    assert "same staleness predicate" in runbook
    assert "pending or claimed webhook delivery" in runbook
    assert "maintenance queue" in runbook and "consumer" in runbook
    assert "raw evidence export" in runbook
    assert "explicit non-default reason" in runbook
    assert "audit" in runbook and "fail" in runbook and "closed" in runbook
    assert "active encryption" in runbook and "m2.9" in runbook
