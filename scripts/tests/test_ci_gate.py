from __future__ import annotations

import os
import subprocess
import textwrap
import unittest
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"


class CiGateTests(unittest.TestCase):
    def run_gate(self, **results: str) -> subprocess.CompletedProcess[str]:
        # Execute the real final gate with GitHub's result strings, including
        # the cancelled siblings produced by matrix fail-fast.
        workflow = WORKFLOW.read_text(encoding="utf-8")
        _, marker, gate = workflow.partition("      - name: Check required jobs\n")
        self.assertTrue(marker)
        _, marker, script = gate.partition("        run: |\n")
        self.assertTrue(marker)
        env = {
            **os.environ,
            "CHANGES_RESULT": "success",
            "BRANCH_POLICY_RESULT": "success",
            "USER_FACING_RESULT": "success",
            "NO_INTRIC_RESULT": "success",
            "CHECKS_RESULT": "success",
            "SELECTED_CHECKS": '["frontend"]',
            **results,
        }
        return subprocess.run(
            ["bash", "-e", "-c", textwrap.dedent(script)],
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )

    def test_successful_selected_checks_pass(self) -> None:
        self.assertEqual(self.run_gate().returncode, 0)

    def test_docs_only_pr_can_skip_expensive_checks(self) -> None:
        result = self.run_gate(CHECKS_RESULT="skipped", SELECTED_CHECKS="[]")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_non_pr_events_can_skip_pr_only_gates(self) -> None:
        result = self.run_gate(BRANCH_POLICY_RESULT="skipped", USER_FACING_RESULT="skipped")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_failed_or_cancelled_checks_never_pass(self) -> None:
        for result in ["failure", "cancelled", "timed_out", ""]:
            with self.subTest(result=result):
                self.assertNotEqual(self.run_gate(CHECKS_RESULT=result).returncode, 0)

    def test_expected_checks_cannot_be_skipped(self) -> None:
        self.assertNotEqual(self.run_gate(CHECKS_RESULT="skipped").returncode, 0)

    def test_missing_scope_cannot_pass_as_docs_only(self) -> None:
        for result in ["failure", "cancelled", "skipped"]:
            with self.subTest(result=result):
                gate = self.run_gate(
                    CHANGES_RESULT=result, CHECKS_RESULT="skipped", SELECTED_CHECKS="[]"
                )
                self.assertNotEqual(gate.returncode, 0)

    def test_failed_preflight_cannot_pass_with_a_skipped_matrix(self) -> None:
        for key in ["BRANCH_POLICY_RESULT", "USER_FACING_RESULT", "NO_INTRIC_RESULT"]:
            with self.subTest(key=key):
                gate = self.run_gate(**{key: "failure", "CHECKS_RESULT": "skipped"})
                self.assertNotEqual(gate.returncode, 0)


if __name__ == "__main__":
    unittest.main()
