"""Summarize retained image reports; never interpret a missing scan as clean."""

import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

VARIANTS = (
    "backend-debian-refresh",
    "backend-debian-wheels",
    "backend-debian-system",
    "backend-wolfi",
    "frontend-debian",
    "frontend-chainguard",
)


@dataclass(frozen=True)
class Finding:
    variant: str
    scanner: str
    target: str
    package: str
    advisory: str
    severity: str
    installed: str
    fixed: str
    status: str


def read_findings(directory: Path, variant: str, scanner: str) -> list[Finding]:
    report = json.loads((directory / f"{scanner}.json").read_text())
    findings = []
    if scanner == "trivy":
        if not isinstance(report.get("Results"), list):
            raise ValueError("Trivy report has no Results array")
        for result in report["Results"]:
            for finding in result.get("Vulnerabilities") or []:
                if finding["Severity"].upper() not in ("HIGH", "CRITICAL"):
                    continue
                findings.append(
                    Finding(
                        variant,
                        scanner,
                        result["Target"],
                        finding["PkgName"],
                        finding["VulnerabilityID"],
                        finding["Severity"].upper(),
                        finding["InstalledVersion"],
                        finding.get("FixedVersion", ""),
                        finding.get("Status", "unknown"),
                    )
                )
    else:
        if not isinstance(report.get("matches"), list):
            raise ValueError("Grype report has no matches array")
        for match in report["matches"]:
            finding, artifact = match["vulnerability"], match["artifact"]
            if finding["severity"].upper() not in ("HIGH", "CRITICAL"):
                continue
            fix = finding.get("fix") or {}
            findings.append(
                Finding(
                    variant,
                    scanner,
                    artifact["type"],
                    artifact["name"],
                    finding["id"],
                    finding["severity"].upper(),
                    artifact["version"],
                    ";".join(fix.get("versions") or []),
                    fix.get("state", "unknown"),
                )
            )
    return findings


def summarize(root: Path) -> bool:
    lines = [
        "# Runtime distribution comparison",
        "",
        "Diagnostic experiment only; no images were published. Counts are scanner findings, "
        "not verified exploit paths. Debian backports and upstream CPE matches need triage.",
        "",
        "All candidates use one checksummed Trivy/Grype database snapshot and Python 3.11 / Node 22. "
        "The refresh backend restores #1040's base lock and audio owner; wheels uses #1040's "
        "lock/audio; system additionally links lxml to Debian's libraries. Wolfi is #1040's image.",
        "",
        "Runtime checks exercise the same behavior, without Wolfi-specific version/path assertions. "
        "Audio tests include new cancellation/format contracts: failures on the refresh candidate "
        "are evidence to inspect, not proof that Debian is incompatible.",
        "",
        "| Candidate | Build | Scan gate | Runtime | Trivy H/C (unique advisories) | Grype H/C (unique advisories) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    all_findings: list[Finding] = []
    details: list[str] = []
    complete = True
    database_checksums: set[str] = set()
    for variant in VARIANTS:
        directory = root / f"comparison-{variant}"
        outcomes_path = directory / "outcomes.json"
        if not outcomes_path.exists():
            lines.append(
                f"| {variant} | MISSING | MISSING | MISSING | MISSING | MISSING |"
            )
            complete = False
            continue
        outcomes = json.loads(outcomes_path.read_text())
        checksum_path = directory / "database-checksums.txt"
        if checksum_path.exists():
            database_checksums.add(checksum_path.read_text())
        else:
            complete = False
        counts = []
        details.extend(["", f"## {variant}", ""])
        for scanner in ("trivy", "grype"):
            try:
                findings = read_findings(directory, variant, scanner)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                counts.append("MISSING/INVALID")
                details.append(f"{scanner}: incomplete report ({type(exc).__name__}).")
                complete = False
                continue
            all_findings.extend(findings)
            critical = sum(f.severity == "CRITICAL" for f in findings)
            high = len(findings) - critical
            unique = len({f.advisory for f in findings})
            counts.append(f"{high}/{critical} ({unique})")
            packages = Counter(f.package for f in findings)
            details.append(
                f"{scanner}: "
                + (
                    ", ".join(
                        f"`{name}` ({count})" for name, count in packages.most_common()
                    )
                    or "No HIGH/CRITICAL findings in the retained report."
                )
            )
            details.append("")
        lines.append(
            f"| {variant} | {outcomes['build']} | {outcomes['scan']} | {outcomes['runtime']} | "
            + " | ".join(counts)
            + " |"
        )
        if outcomes["build"] != "success" or outcomes["scan"] not in (
            "success",
            "failure",
        ):
            complete = False
    if len(database_checksums) != 1:
        complete = False
        lines.extend(
            [
                "",
                "**Database provenance missing or differs: comparison is incomplete.**",
            ]
        )
    lines.extend(
        [
            "",
            "Full package/advisory/version/fix-status rows are in `findings.csv`. "
            "Raw reports, source and database checksums, image IDs, build logs and runtime "
            "logs are retained in each candidate artifact.",
        ]
    )
    if not complete:
        lines.extend(
            [
                "",
                "**INCOMPLETE: missing/failed builds or scan evidence must not be treated as clean.**",
            ]
        )
    lines.extend(details)
    (root / "comparison.md").write_text("\n".join(lines) + "\n")
    with (root / "findings.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(Finding.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(finding) for finding in all_findings)
    return complete


if __name__ == "__main__":
    raise SystemExit(0 if summarize(Path(sys.argv[1])) else 1)
