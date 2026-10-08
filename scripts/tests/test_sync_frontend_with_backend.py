from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "sync-frontend-with-backend.sh"


class FrontendSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        self.script = scripts / SCRIPT.name
        shutil.copyfile(SCRIPT, self.script)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(self.root / "calls"),
        }
        self.command("sleep", "exit 0")
        self.command(
            "docker",
            """echo "$*" >> "$CALLS"
case "$1" in
    inspect) echo true ;;
    logs) echo 'backend configuration rejected' ;;
esac
""",
        )

    def command(self, name: str, body: str) -> None:
        command = self.bin / name
        command.write_text(f"#!/bin/bash\n{body}\n")
        command.chmod(0o755)

    def run_sync(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script), "test-backend:latest"],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_unresponsive_openapi_is_bounded_and_reports_backend_logs(self) -> None:
        self.command(
            "curl",
            """echo "curl $*" >> "$CALLS"
case " $* " in
    *" --max-time "*) exit 28 ;;
    *) echo 'unbounded OpenAPI request' >&2; exec /bin/sleep 10 ;;
esac
""",
        )

        result = self.run_sync()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backend configuration rejected", result.stderr)
        self.assertIn("rm -f temp-backend-", (self.root / "calls").read_text())

    def test_ready_response_supplies_version_without_another_request(self) -> None:
        self.command(
            "curl",
            """echo "curl $*" >> "$CALLS"
echo '{"info":{"version":"test-build-123"}}'
""",
        )

        result = self.run_sync()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Backend version: test-build-123", result.stdout)
        calls = (self.root / "calls").read_text().splitlines()
        self.assertEqual(sum(line.startswith("curl ") for line in calls), 1)

    def test_failed_download_does_not_accept_partial_output(self) -> None:
        self.command(
            "curl",
            """echo '{"info":{"version":"partial"}}'
exit 28
""",
        )
        self.command(
            "docker",
            """echo "$*" >> "$CALLS"
case "$1" in
    inspect) echo false ;;
    logs) echo 'backend configuration rejected' ;;
esac
""",
        )

        result = self.run_sync()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Backend container exited", result.stderr)
        self.assertIn("backend configuration rejected", result.stderr)
        self.assertNotIn("Frontend synchronization completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
