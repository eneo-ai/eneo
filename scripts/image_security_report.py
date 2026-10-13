#!/usr/bin/env python3
"""Present both image scanners without treating package matches as exploits."""

import argparse
import csv
import hashlib
import html
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SEVERITIES = ("UNKNOWN", "NEGLIGIBLE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def rows(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return value


def field(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing non-empty text field")
    return value


def severity(value: object) -> str:
    result = field(value).upper()
    if result not in SEVERITIES:
        raise ValueError(f"Unsupported scanner severity: {result!r}")
    return result


@dataclass(frozen=True)
class Match:
    scanner: str
    advisory: str
    package: str
    installed: str
    severity: str
    fixed: str
    fix_status: str
    description: str = ""


def read_matches(directory: Path) -> list[Match]:
    status = json.loads((directory / "scan-status.json").read_text())
    if status != {"trivy": 0, "grype": 0}:
        raise ValueError("Both scanners must complete successfully")
    trivy = record(json.loads((directory / "trivy.json").read_text()))
    grype = record(json.loads((directory / "grype.json").read_text()))
    if trivy.get("SchemaVersion") != 2:
        raise ValueError("Unsupported Trivy report schema")
    if record(grype["descriptor"]).get("name") != "grype":
        raise ValueError("Not a Grype report")
    matches = []
    for result in rows(trivy["Results"]):
        for raw in rows(record(result).get("Vulnerabilities", [])):
            item = record(raw)
            matches.append(
                Match(
                    "Trivy",
                    field(item["VulnerabilityID"]),
                    field(item["PkgName"]),
                    field(item["InstalledVersion"]),
                    severity(item["Severity"]),
                    str(item.get("FixedVersion") or ""),
                    str(item.get("Status") or "unknown"),
                    str(item.get("Title") or item.get("Description") or ""),
                )
            )
    for raw in rows(grype["matches"]):
        item = record(raw)
        vulnerability, package = record(item["vulnerability"]), record(item["artifact"])
        advisory = field(vulnerability["id"])
        # Use a CVE alias only when unambiguous. Retain scanner-native IDs otherwise.
        aliases = {
            field(record(alias)["id"])
            for alias in rows(item.get("relatedVulnerabilities", []))
        }
        cves = {
            alias
            for alias in aliases | {advisory}
            if re.fullmatch(r"CVE-\d{4}-\d+", alias)
        }
        if len(cves) == 1:
            advisory = cves.pop()
        fix = record(vulnerability["fix"])
        matches.append(
            Match(
                "Grype",
                advisory,
                field(package["name"]),
                field(package["version"]),
                severity(vulnerability["severity"]),
                ", ".join(field(version) for version in rows(fix["versions"])),
                field(fix["state"]),
                str(vulnerability.get("description") or ""),
            )
        )
    return sorted(
        set(matches),
        key=lambda item: (item.advisory, item.package, item.scanner, item.installed),
    )


def text(value: str) -> str:
    """Scanner/package data must not inject Markdown or HTML into summaries."""
    return (
        html.escape(value)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def csv_text(value: str) -> str:
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def reports(
    matches: list[Match], component: str, image: str
) -> tuple[str, dict[str, object]]:
    grouped: defaultdict[str, list[Match]] = defaultdict(list)
    for match in matches:
        grouped[match.advisory].append(match)
    ordered = sorted(
        grouped,
        key=lambda advisory: (
            -max(SEVERITIES.index(item.severity) for item in grouped[advisory]),
            advisory,
        ),
    )
    counts = Counter(
        max((item.severity for item in group), key=SEVERITIES.index)
        for group in grouped.values()
    )
    heading = [
        f"## Image security: {component}",
        "",
        f"Image: `{text(image)}`",
        "",
        f"Completed (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "Both scanners completed. Counts are advisory/package matches, **not confirmed exploit paths**.",
        "Scanner disagreements and unavailable fixes remain visible; no findings are suppressed.",
        "",
        "| Unique advisory severity (highest scanner rating) | Count |",
        "| --- | ---: |",
        *[f"| {level} | {counts[level]} |" for level in reversed(SEVERITIES)],
        "",
        "| Scanner | Package/advisory matches | HIGH / CRITICAL |",
        "| --- | ---: | ---: |",
    ]
    for scanner in ("Trivy", "Grype"):
        selected = [item for item in matches if item.scanner == scanner]
        heading.append(
            f"| {scanner} | {len(selected)} | {sum(item.severity in ('HIGH', 'CRITICAL') for item in selected)} |"
        )
    heading += [
        "",
        "| Advisory | Scanner severity | Affected packages | Fix information |",
        "| --- | --- | --- | --- |",
    ]
    rules, results = [], []
    for index, advisory in enumerate(ordered):
        group = grouped[advisory]
        level = max((item.severity for item in group), key=SEVERITIES.index)
        ratings = "; ".join(
            sorted({f"{item.scanner}: {item.severity}" for item in group})
        )
        packages = ", ".join(sorted({item.package for item in group}))
        fixes = "; ".join(
            sorted(
                {f"{item.scanner}: {item.fixed or item.fix_status}" for item in group}
            )
        )
        if index < 40:
            heading.append(
                f"| {text(advisory)} | {text(ratings)} | {text(packages)} | {text(fixes)} |"
            )
        # Keep lower-severity detail in CSV/JSON; actionable alerts start at HIGH.
        if level not in ("HIGH", "CRITICAL"):
            continue
        description = next(
            (item.description for item in group if item.description),
            "No description supplied",
        )
        detail = "\n".join(
            f"{item.scanner}: {item.package} {item.installed}; {item.severity}; "
            f"fixed versions: {item.fixed or 'not reported'}; status: {item.fix_status}"
            for item in group
        )
        rules.append(
            {
                "id": advisory,
                "shortDescription": {"text": f"{advisory} in container packages"},
                # Map qualitative scanner levels to SARIF bands, not a calculated CVSS.
                "properties": {
                    "security-severity": "9.0" if level == "CRITICAL" else "7.0",
                    "tags": ["security", "container", "dependency"],
                },
                "help": {
                    "text": description
                    + "\n\nPackage inventory match; assess reachability and vendor backports before assigning application impact. "
                    "The Dockerfile location identifies the image owner, not a vulnerable source line."
                },
            }
        )
        results.append(
            {
                "ruleId": advisory,
                "level": "error",
                "message": {
                    "text": f"{advisory}: review {component} container dependencies\n{description}\nImage: {image}\n{detail}\n"
                    "Not a confirmed Eneo exploit. Qualitative severity is the highest scanner rating."
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f"{component}/Dockerfile"},
                            "region": {"startLine": 1},
                        }
                    }
                ],
                # Digest and package versions are evidence, never part of alert identity.
                "partialFingerprints": {
                    "imageAdvisory/v1": hashlib.sha256(
                        f"{component}:{advisory}".encode()
                    ).hexdigest()
                },
            }
        )
    heading += [
        "",
        "First 40 advisories shown; **findings.csv** and **findings.json** contain every match.",
        "HIGH/CRITICAL blocks the candidate. A published-image failure requests maintenance; it does not stop running containers.",
        "See docs/SECURITY.md for triage, ownership, notifications and remediation.",
        "",
    ]
    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Eneo image security",
                        "version": "1.0.0",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return "\n".join(heading), sarif


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--component", choices=("backend", "frontend"), required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    sarif_path = args.directory / "image-security.sarif"
    sarif_path.unlink(missing_ok=True)
    try:
        matches = read_matches(args.directory)
        summary, sarif = reports(matches, args.component, args.image)
        (args.directory / "findings.json").write_text(
            json.dumps([asdict(item) for item in matches], indent=2) + "\n"
        )
        with (args.directory / "findings.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(Match.__dataclass_fields__)
            writer.writerows(
                [csv_text(value) for value in asdict(item).values()] for item in matches
            )
        sarif_path.write_text(json.dumps(sarif, indent=2) + "\n")
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a") as stream:
                stream.write("sarif-ready=true\n")
        code = int(any(item.severity in ("HIGH", "CRITICAL") for item in matches))
    except (ValueError, KeyError, TypeError, OSError) as error:
        summary = (
            f"## Image security: {args.component}\n\n**INCOMPLETE — not a clean scan.**\n\n"
            f"Image: `{text(args.image)}`\n\n{text(str(error))}\n\n"
            "No SARIF result is uploaded: existing alerts must not be closed by missing evidence. "
            "Inspect the scanner logs and retained reports.\n"
        )
        code = 2
    (args.directory / "summary.md").write_text(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a") as stream:
            stream.write(summary + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
