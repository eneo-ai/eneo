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
import eneo.worker.arq as arq_worker
assert arq_worker.WorkerSettings.functions
"""
    )


def test_user_and_config_import_cleanly_in_either_order() -> None:
    _run_python_import_probe(
        """
import eneo.users.user
import eneo.main.config
"""
    )
    _run_python_import_probe(
        """
import eneo.main.config
import eneo.users.user
"""
    )


def test_flow_recovery_policy_import_keeps_domain_models_and_principal_lazy() -> None:
    _run_python_import_probe(
        """
import sys

import eneo.flows.domain.flow_run_recovery_policy

eager_imports = {
    name for name in (
        "eneo.flows.domain.flow",
        "eneo.flows.principal",
        "eneo.users.user",
    )
    if name in sys.modules
}
if eager_imports:
    raise SystemExit(f"unexpected eager imports: {sorted(eager_imports)}")
"""
    )
