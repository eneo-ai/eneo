from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _run_python_import_probe(source: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout


def test_worker_settings_import_does_not_reenter_partially_initialized_user() -> None:
    _run_python_import_probe(
        """
import intric.worker.arq as arq_worker
assert arq_worker.WorkerSettings.functions
"""
    )


def test_flow_recovery_policy_import_keeps_runtime_principal_lazy() -> None:
    _run_python_import_probe(
        """
import sys

import intric.flows.application.flow_run_recovery_policy

eager_imports = {
    name for name in ("intric.flows.principal", "intric.users.user")
    if name in sys.modules
}
if eager_imports:
    raise SystemExit(f"unexpected eager imports: {sorted(eager_imports)}")
"""
    )
