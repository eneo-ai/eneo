import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "image_security_report.py"
SPEC = importlib.util.spec_from_file_location("image_security_report", SCRIPT)
report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report
SPEC.loader.exec_module(report)


class ImageSecurityReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.write("scan-status.json", {"trivy": 0, "grype": 0})
        self.write("trivy.json", {"SchemaVersion": 2, "Results": []})
        self.write("grype.json", {"descriptor": {"name": "grype"}, "matches": []})

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def execute(self):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--directory",
                str(self.directory),
                "--component",
                "backend",
                "--image",
                "example@sha256:" + "a" * 64,
            ],
            env={
                **os.environ,
                "GITHUB_STEP_SUMMARY": str(self.directory / "step.md"),
                "GITHUB_OUTPUT": str(self.directory / "output"),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_valid_empty_reports_publish_empty_analysis(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        sarif = json.loads((self.directory / "image-security.sarif").read_text())
        self.assertEqual(sarif["runs"][0]["results"], [])
        self.assertIn("sarif-ready=true", (self.directory / "output").read_text())

    def test_missing_or_failed_scanner_never_closes_existing_alerts(self):
        for status in ({"trivy": 0, "grype": 1}, {}, {"trivy": 1, "grype": 0}):
            with self.subTest(status=status):
                self.write("scan-status.json", status)
                (self.directory / "image-security.sarif").write_text("stale")
                self.assertEqual(self.execute().returncode, 2)
                self.assertFalse((self.directory / "image-security.sarif").exists())
                self.assertIn("INCOMPLETE", (self.directory / "step.md").read_text())
        (self.directory / "grype.json").unlink()
        self.write("scan-status.json", {"trivy": 0, "grype": 0})
        self.assertEqual(self.execute().returncode, 2)

    def test_invalid_json_or_schema_cannot_look_clean(self):
        for content in (
            "{",
            "{}",
            '{"SchemaVersion":2,"Results":null}',
            '{"SchemaVersion":99,"Results":[]}',
        ):
            with self.subTest(content=content):
                (self.directory / "trivy.json").write_text(content)
                self.assertEqual(self.execute().returncode, 2)
                self.assertFalse((self.directory / "image-security.sarif").exists())

    def test_all_packages_and_disagreements_survive_one_advisory_alert(self):
        matches = [
            report.Match(
                "Trivy", "CVE-2026-1234", "ffmpeg", "1", "MEDIUM", "2", "fixed"
            ),
            report.Match(
                "Grype", "CVE-2026-1234", "ffmpeg", "1", "CRITICAL", "", "not-fixed"
            ),
            report.Match(
                "Grype", "CVE-2026-1234", "libavcodec", "1", "CRITICAL", "", "not-fixed"
            ),
        ]
        summary, sarif = report.reports(matches, "backend", "image@sha256:a")
        results = sarif["runs"][0]["results"]
        self.assertEqual(len(results), 1)
        for expected in ("libavcodec", "Trivy: MEDIUM", "Grype: CRITICAL", "not-fixed"):
            self.assertIn(expected, summary)
        self.assertIn("not reported", results[0]["message"]["text"])
        self.assertEqual(
            sarif["runs"][0]["tool"]["driver"]["rules"][0]["properties"][
                "security-severity"
            ],
            "9.0",
        )

    def test_alert_identity_survives_rebuild_and_package_update(self):
        def identity(version, digest):
            match = report.Match(
                "Trivy", "CVE-2026-1234", "parser", version, "HIGH", "", "affected"
            )
            _, sarif = report.reports([match], "backend", digest)
            result = sarif["runs"][0]["results"][0]
            return result["ruleId"], result["partialFingerprints"], result["locations"]

        self.assertEqual(identity("1", "image:a"), identity("2", "image:b"))

    def test_lower_severities_remain_visible_without_high_alert_noise(self):
        summary, sarif = report.reports(
            [
                report.Match(
                    "Grype", "CVE-2026-1234", "parser", "1", "MEDIUM", "", "not-fixed"
                ),
            ],
            "backend",
            "image",
        )
        self.assertIn("CVE-2026-1234", summary)
        self.assertEqual(sarif["runs"][0]["results"], [])

    def test_alias_normalization_and_unfixed_critical_gate(self):
        self.write(
            "grype.json",
            {
                "descriptor": {"name": "grype"},
                "matches": [
                    {
                        "vulnerability": {
                            "id": "GHSA-example",
                            "severity": "Critical",
                            "fix": {"state": "wont-fix", "versions": []},
                        },
                        "relatedVulnerabilities": [{"id": "CVE-2026-1234"}],
                        "artifact": {"name": "parser", "version": "1"},
                    }
                ],
            },
        )
        self.assertEqual(self.execute().returncode, 1)
        self.assertTrue((self.directory / "image-security.sarif").exists())
        matches = report.read_matches(self.directory)
        self.assertEqual(matches[0].advisory, "CVE-2026-1234")
        self.assertEqual(matches[0].fix_status, "wont-fix")
        self.assertIn("wont-fix", (self.directory / "findings.csv").read_text())

    def test_untrusted_package_names_cannot_inject_summary_or_csv_formula(self):
        summary, _ = report.reports(
            [
                report.Match(
                    "Trivy",
                    "CVE-2026-1234",
                    "<script>|\n# injected",
                    "1",
                    "HIGH",
                    "",
                    "affected",
                ),
            ],
            "frontend",
            "image",
        )
        self.assertNotIn("<script>", summary)
        self.assertNotIn("\n# injected", summary)
        self.assertEqual(report.csv_text("=IMPORTDATA(1)"), "'=IMPORTDATA(1)")


if __name__ == "__main__":
    unittest.main()
