#!/usr/bin/env python3
import argparse
import json
import os
import sys


def normalize_path(value: str) -> str:
    if not value:
        return ""
    path = value.replace("\\", "/")
    if "/backend/" in path:
        path = path.split("/backend/")[-1]
    return path.lstrip("./")


def normalize_diag(diag: dict) -> dict:
    file_path = normalize_path(diag.get("file", ""))
    rule = diag.get("rule", "")
    message = diag.get("message", "")
    severity = diag.get("severity", "")
    diag_range = diag.get("range") or {}
    start = diag_range.get("start") or {}
    end = diag_range.get("end") or {}
    return {
        "file": file_path,
        "rule": rule,
        "message": message,
        "severity": severity,
        "range": {
            "start": {
                "line": start.get("line"),
                "character": start.get("character"),
            },
            "end": {
                "line": end.get("line"),
                "character": end.get("character"),
            },
        },
    }


def diag_key(diag: dict, ignore_range: bool) -> tuple:
    normalized = normalize_diag(diag)
    if ignore_range:
        return (
            normalized["file"],
            normalized["rule"],
            normalized["message"],
            normalized["severity"],
        )
    start = normalized["range"]["start"]
    end = normalized["range"]["end"]
    return (
        normalized["file"],
        normalized["rule"],
        normalized["message"],
        start.get("line"),
        start.get("character"),
        end.get("line"),
        end.get("character"),
    )


def load_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def format_diag(diag: dict) -> str:
    normalized = normalize_diag(diag)
    file_path = normalized["file"] or "<unknown>"
    start = normalized["range"]["start"]
    line = start.get("line")
    character = start.get("character")
    if line is not None:
        line += 1
    if character is not None:
        character += 1
    location = file_path
    if line is not None and character is not None:
        location = f"{file_path}:{line}:{character}"
    severity = normalized.get("severity") or "error"
    rule = normalized.get("rule")
    rule_text = f" [{rule}]" if rule else ""
    message = normalized.get("message") or ""
    return f"{location}: {severity}{rule_text}: {message}"


def is_error(diag: dict) -> bool:
    return (diag.get("severity") or "").lower() == "error"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare pyright diagnostics against a baseline."
    )
    parser.add_argument("--baseline", required=True, help="Baseline JSON file")
    parser.add_argument("--current", required=True, help="Current pyright JSON file")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write normalized baseline JSON from current diagnostics",
    )
    parser.add_argument(
        "--include-warnings",
        action="store_true",
        help="Include warning-level diagnostics in comparisons",
    )
    parser.add_argument(
        "--ignore-range",
        action="store_true",
        help="Ignore line/column ranges when comparing diagnostics",
    )
    args = parser.parse_args()

    ignore_range = args.ignore_range or os.environ.get(
        "RATCHET_IGNORE_RANGE", ""
    ).lower() in (
        "1",
        "true",
    )

    try:
        current_data = load_json(args.current)
    except Exception as exc:
        print(f"Failed to read current diagnostics: {exc}", file=sys.stderr)
        return 2

    if args.write_baseline:
        baseline_data = dict(current_data)
        baseline_data["generalDiagnostics"] = [
            normalize_diag(diag) for diag in current_data.get("generalDiagnostics", [])
        ]
        try:
            write_json(args.baseline, baseline_data)
        except Exception as exc:
            print(f"Failed to write baseline: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        baseline_data = load_json(args.baseline)
    except Exception as exc:
        print(f"Failed to read baseline diagnostics: {exc}", file=sys.stderr)
        return 2

    baseline_diags = baseline_data.get("generalDiagnostics", [])
    current_diags = current_data.get("generalDiagnostics", [])
    if not args.include_warnings:
        baseline_diags = [diag for diag in baseline_diags if is_error(diag)]
        current_diags = [diag for diag in current_diags if is_error(diag)]
    baseline_keys = {diag_key(diag, ignore_range) for diag in baseline_diags}

    new_diags = [
        diag
        for diag in current_diags
        if diag_key(diag, ignore_range) not in baseline_keys
    ]

    if not new_diags:
        return 0

    new_diags.sort(
        key=lambda diag: (
            normalize_path(diag.get("file", "")),
            (diag.get("range") or {}).get("start", {}).get("line") or 0,
            (diag.get("range") or {}).get("start", {}).get("character") or 0,
            diag.get("rule") or "",
        )
    )

    print(
        f"New pyright diagnostics not in baseline ({len(new_diags)}):",
        file=sys.stderr,
    )
    for diag in new_diags:
        print(format_diag(diag), file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
