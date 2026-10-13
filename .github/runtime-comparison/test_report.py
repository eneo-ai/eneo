import json
import tempfile
import unittest
from pathlib import Path

from report import VARIANTS, read_findings, summarize


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def candidate(self, variant):
        directory = self.root / f"comparison-{variant}"
        directory.mkdir()
        (directory / "outcomes.json").write_text(
            json.dumps(
                {
                    "build": "success",
                    "scan": "success",
                    "runtime": "success",
                }
            )
        )
        (directory / "database-checksums.txt").write_text("same frozen databases")
        (directory / "trivy.json").write_text('{"Results": []}')
        (directory / "grype.json").write_text('{"matches": []}')
        return directory

    def test_missing_candidate_cannot_look_clean(self):
        self.assertFalse(summarize(self.root))
        self.assertIn("INCOMPLETE", (self.root / "comparison.md").read_text())

    def test_zero_findings_requires_all_reports_and_same_databases(self):
        for variant in VARIANTS:
            self.candidate(variant)
        self.assertTrue(summarize(self.root))
        directory = self.root / f"comparison-{VARIANTS[0]}"
        (directory / "database-checksums.txt").write_text("different databases")
        self.assertFalse(summarize(self.root))

    def test_malformed_report_cannot_look_clean(self):
        for variant in VARIANTS:
            self.candidate(variant)
        (self.root / f"comparison-{VARIANTS[0]}" / "grype.json").write_text("{}")
        self.assertFalse(summarize(self.root))

    def test_report_keeps_unfixed_findings_and_deduplicates_only_advisory_count(self):
        directory = self.candidate(VARIANTS[0])
        finding = {
            "PkgName": "libavcodec",
            "VulnerabilityID": "CVE-example",
            "Severity": "HIGH",
            "InstalledVersion": "1",
            "Status": "affected",
        }
        other = dict(finding, PkgName="ffmpeg")
        (directory / "trivy.json").write_text(
            json.dumps(
                {
                    "Results": [
                        {"Target": "Debian", "Vulnerabilities": [finding, other]}
                    ],
                }
            )
        )
        rows = read_findings(directory, VARIANTS[0], "trivy")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row.advisory for row in rows}), 1)
        self.assertTrue(
            all(row.fixed == "" and row.status == "affected" for row in rows)
        )
        (directory / "grype.json").write_text(
            json.dumps(
                {
                    "matches": [
                        {
                            "artifact": {
                                "name": "libavcodec",
                                "type": "deb",
                                "version": "1",
                            },
                            "vulnerability": {
                                "id": "CVE-example",
                                "severity": "High",
                                "fix": {"state": "not-fixed", "versions": []},
                            },
                        }
                    ]
                }
            )
        )
        self.assertEqual(
            read_findings(directory, VARIANTS[0], "grype")[0].status, "not-fixed"
        )


if __name__ == "__main__":
    unittest.main()
