"""Exercise bootstrap imports in a fresh interpreter, as db-init does."""

import os
import subprocess
import sys
from pathlib import Path


def test_bootstrap_role_permissions_do_not_import_runtime_services():
    backend_dir = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "POSTGRES_USER": "test",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from init_db import _predefined_role_permissions
permissions = _predefined_role_permissions("Owner")
assert "admin" in permissions
assert "flows_manage" in permissions
assert "eneo.audit.application.audit_service" not in sys.modules
assert "eneo.worker.redis" not in sys.modules
""",
        ],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
