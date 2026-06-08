#!/usr/bin/env python3
"""Surface the least-covered files from the frontend (vitest) and backend
(coverage.py) JSON reports, so untested code is easy to spot. Read-only: it just
summarizes reports produced by scripts/coverage.sh — it runs no tests itself."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FE_JSON = os.path.join(ROOT, "frontend/apps/web/coverage/coverage-summary.json")
BE_JSON = os.path.join(ROOT, "backend/coverage.json")
TOP = 20


def _bar(pct):
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def _load_frontend():
    with open(FE_JSON) as f:
        data = json.load(f)
    files = []
    total = None
    for path, m in data.items():
        lines = m.get("lines", {})
        pct = lines.get("pct", 0) or 0
        uncovered = (lines.get("total", 0) or 0) - (lines.get("covered", 0) or 0)
        if path == "total":
            total = pct
            continue
        rel = path.replace(ROOT + "/", "")
        files.append((rel, pct, uncovered))
    return total, files


def _load_backend():
    with open(BE_JSON) as f:
        data = json.load(f)
    files = []
    for path, m in data.get("files", {}).items():
        s = m.get("summary", {})
        pct = s.get("percent_covered", 0) or 0
        uncovered = len(m.get("missing_lines", [])) or s.get("missing_lines", 0) or 0
        files.append((path, pct, uncovered))
    total = data.get("totals", {}).get("percent_covered")
    return total, files


def _report(title, total, files):
    print(f"\n\033[1m{title}\033[0m", end="")
    if total is not None:
        print(f"  —  overall {total:.0f}%  {_bar(total)}")
    else:
        print()
    gaps = sorted((f for f in files if f[1] < 100), key=lambda f: (f[1], -f[2]))
    untested = [f for f in gaps if f[1] == 0]
    if not gaps:
        print("  ✔ every included file is fully covered")
        return
    if untested:
        print(f"  \033[31mCompletely untested ({len(untested)}):\033[0m")
        for rel, _pct, unc in untested[:TOP]:
            print(f"    {rel}  ({unc} lines)")
    partial = [f for f in gaps if f[1] > 0]
    if partial:
        print("  Least covered:")
        for rel, pct, unc in partial[:TOP]:
            print(f"    {pct:5.0f}%  {_bar(pct)}  {rel}  ({unc} uncovered)")
    shown = min(len(untested), TOP) + min(len(partial), TOP)
    if len(gaps) > shown:
        print(f"    … and {len(gaps) - shown} more files with gaps — see the HTML report")


def main():
    print("\n\033[1m══ Where is the code untested? ══\033[0m")
    if os.path.exists(FE_JSON):
        _report("Frontend (vitest)", *_load_frontend())
    else:
        print("\n\033[1mFrontend (vitest)\033[0m\n  (no report — run with frontend enabled)")
    if os.path.exists(BE_JSON):
        _report("Backend (pytest)", *_load_backend())
    else:
        print("\n\033[1mBackend (pytest)\033[0m\n  (no report — run with backend enabled)")
    print()


if __name__ == "__main__":
    sys.exit(main())
