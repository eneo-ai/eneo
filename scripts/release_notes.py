#!/usr/bin/env python3
"""Move What's new notes through the release flow without hand-picking versions.

Contributors on develop write every entry into the "next" block. Its version
and date follow from the release process, not from the author:

  cut X.Y           on a new release/vX.Y branch: "next" becomes X.Y.0
  finalize X.Y.Z    on release/vX.Y before the final tag: sets the date and
                    runs the tag rule the image build will run
  port X.Y.Z        on develop after the final tag: copies the dated release
                    from the release branch and drops its entries from "next"

Each command edits only releases.json, runs scripts/check_whats_new.py with
the rules of the branch it is meant for, restores the file when they fail and
prints the git steps. It never commits, tags or pushes.

Run from the repository root:  python3 scripts/release_notes.py cut 2.4
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from .check_whats_new import (
        RELEASES_PATH,
        SCHEMA_PATH,
        Vocabulary,
        _core_version,
        _semver_key,
        check,
        report,
    )
else:
    from check_whats_new import (  # type: ignore[no-redef]
        RELEASES_PATH,
        SCHEMA_PATH,
        Vocabulary,
        _core_version,
        _semver_key,
        check,
        report,
    )

LINE_RE = re.compile(r"^(\d+)\.(\d+)$")
FINAL_RE = re.compile(r"^(\d+)\.(\d+)\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRINT_WIDTH = 100  # frontend/packages/whats-new/.prettierrc


class Abort(Exception):
    pass


def format_json(value: object, indent: int = 0, prefix: str = "") -> str:
    """Serialise the way prettier formats releases.json, so the package's
    lint passes without running node: objects always break, arrays of
    scalars stay on one line when they fit."""
    pad = " " * indent
    if isinstance(value, dict) and value:
        lines = []
        for key, item in value.items():
            name = json.dumps(key, ensure_ascii=False) + ": "
            lines.append(" " * (indent + 2) + name + format_json(item, indent + 2, name))
        return "{\n" + ",\n".join(lines) + "\n" + pad + "}"
    if isinstance(value, list) and value:
        if not any(isinstance(item, (dict, list)) for item in value):
            flat = "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
            # The trailing comma or closing bracket of the parent counts too.
            if indent + len(prefix) + len(flat) + 1 <= PRINT_WIDTH:
                return flat
        lines = [" " * (indent + 2) + format_json(item, indent + 2) for item in value]
        return "[\n" + ",\n".join(lines) + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False)


def _ids(entries: list[dict]) -> set[str]:
    found: set[str] = set()
    for entry in entries:
        found.add(entry["id"])
        found.update(entry.get("aliases", []))
    return found


def _release(version: str, entries: list[dict], date: str | None = None) -> dict:
    release: dict = {"version": version}
    if date:
        release["date"] = date
    release["entries"] = entries
    return release


class Notes:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / RELEASES_PATH
        self.original = self.path.read_text(encoding="utf-8")
        self.data = json.loads(self.original)
        self.vocab = Vocabulary(json.loads((root / SCHEMA_PATH).read_text(encoding="utf-8")))

    @property
    def releases(self) -> list[dict]:
        return self.data["releases"]

    def find(self, version: str) -> dict | None:
        return next((r for r in self.releases if r.get("version") == version), None)

    def upcoming(self) -> dict | None:
        first = self.releases[0] if self.releases else None
        return first if first and first.get("version") == self.vocab.unreleased else None

    def save_checked(self, branch: str, release_tag: str | None = None) -> bool:
        self.path.write_text(format_json(self.data) + "\n", encoding="utf-8")
        _, errors = check(self.root, branch, release_tag)
        if errors:
            self.path.write_text(self.original, encoding="utf-8")
            report(errors)
            print(f"{RELEASES_PATH} is unchanged.")
            return False
        return True


def cut(notes: Notes, line: str) -> list[str]:
    match = LINE_RE.match(line)
    if not match:
        raise Abort(f"cut takes a release line like 2.4, not {line!r}")
    upcoming = notes.upcoming()
    if not upcoming:
        raise Abort(
            f"there is no {notes.vocab.unreleased!r} block to cut; "
            "run this on the new release branch, right after creating it from develop"
        )
    version = f"{line}.0"
    taken = [
        r["version"]
        for r in notes.releases[1:]
        if _semver_key(_core_version(r["version"]))[:2] >= (int(match[1]), int(match[2]))
    ]
    if taken:
        raise Abort(f"{', '.join(taken)} already exists; {version} must be the newest release")
    notes.releases[0] = _release(version, upcoming["entries"])
    branch = f"release/v{line}"
    if not notes.save_checked(branch):
        return []
    return [
        f'Renamed {notes.vocab.unreleased!r} to {version} ({len(upcoming["entries"])} entries).',
        "",
        f"Commit it as the first change on {branch}:",
        f"  git add {RELEASES_PATH}",
        f'  git commit -m "docs(whats-new): name the release notes for v{version}"',
        "",
        f"Develop keeps its {notes.vocab.unreleased!r} block. Fix the {version} text on {branch};",
        f"after the final tag, port it: python3 scripts/release_notes.py port {version}"
        f" --from origin/{branch}",
    ]


def finalize(notes: Notes, version: str, date: str) -> list[str]:
    match = FINAL_RE.match(version)
    if not match:
        raise Abort(f"finalize takes a final version like 2.4.0, not {version!r}")
    if not DATE_RE.match(date):
        raise Abort(f"--date must be YYYY-MM-DD, not {date!r}")
    branch = f"release/v{match[1]}.{match[2]}"
    release = notes.find(version)
    if release:
        notes.releases[notes.releases.index(release)] = _release(
            version, release["entries"], date
        )
        done = f"Dated {version} {date}" + (
            f" (was {release['date']})." if release.get("date") not in (None, date) else "."
        )
    else:
        done = f"No notes for {version}; a hotfix without user-facing changes needs none."
    if not notes.save_checked(branch, f"v{version}"):
        return []
    return [
        done,
        "",
        f"Merge it to {branch} before tagging (the image build reruns this check on v{version}):",
        f"  git add {RELEASES_PATH}",
        f'  git commit -m "docs(whats-new): date the v{version} release notes"',
        "",
        f"After the final tag, on develop: python3 scripts/release_notes.py port {version}"
        f" --from origin/{branch}",
    ]


def port(notes: Notes, version: str, ref: str) -> list[str]:
    if not FINAL_RE.match(version):
        raise Abort(f"port takes a final version like 2.4.0, not {version!r}")
    shown = subprocess.run(
        ["git", "show", f"{ref}:{RELEASES_PATH.as_posix()}"],
        cwd=notes.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        raise Abort(f"cannot read {RELEASES_PATH} at {ref}: {shown.stderr.strip()}")
    released = next(
        (r for r in json.loads(shown.stdout)["releases"] if r.get("version") == version), None
    )
    if released is None:
        raise Abort(f"{ref} has no notes for {version}; there is nothing to port")
    if not released.get("date"):
        raise Abort(f"{version} has no date on {ref}; run finalize there and tag it first")

    upcoming = notes.upcoming()
    previous = notes.find(version)
    # Develop may have added keys the release branch never got (permissions,
    # a showMe for a newer page); the release branch owns the text.
    develop: dict[str, dict] = {
        entry["id"]: entry
        for block in (previous, upcoming)
        if block
        for entry in block["entries"]
    }
    kept: list[str] = []
    rewritten: list[str] = []
    entries = []
    for entry in released["entries"]:
        identities = _ids([entry])
        matches = [ours for ours in develop.values() if _ids([ours]) & identities]
        if matches:
            # A merged entry may match several develop entries. Preserve their
            # shared metadata, but never guess how conflicting requirements combine.
            develop_only = [
                {
                    key: value
                    for key, value in ours.items()
                    if key not in entry and key != "aliases"
                }
                for ours in matches
            ]
            if any(fields != develop_only[0] for fields in develop_only[1:]):
                matched_ids = ", ".join(ours["id"] for ours in matches)
                raise Abort(
                    f"{entry['id']} matches {matched_ids} with conflicting develop-only fields; "
                    "reconcile their metadata before porting"
                )
            ours = matches[0]
            extra = sorted(set(ours) - set(entry))
            if extra:
                kept.append(f"{entry['id']} ({', '.join(extra)})")
            if any(
                (match.get("title"), match.get("body"))
                != (entry.get("title"), entry.get("body"))
                for match in matches
            ):
                rewritten.append(entry["id"])
            aliases = list(
                dict.fromkeys(
                    identity
                    for source in [entry, *matches]
                    for identity in [source["id"], *source.get("aliases", [])]
                    if identity != entry["id"]
                )
            )
            entry = {**ours, **entry}
            if aliases:
                entry["aliases"] = aliases
            else:
                entry.pop("aliases", None)
        entries.append(
            {key: entry[key] for key in notes.vocab.entry_order if key in entry}
        )

    shipped = _ids(entries)
    moved: list[str] = []
    if upcoming:
        remaining = []
        for entry in upcoming["entries"]:
            if _ids([entry]) & shipped:
                moved.append(entry["id"])
            else:
                remaining.append(entry)
        upcoming["entries"] = remaining

    history = [r for r in notes.releases if r is not upcoming and r is not previous]
    key = _semver_key(version)
    position = next(
        (i for i, r in enumerate(history) if _semver_key(r["version"]) < key), len(history)
    )
    history.insert(position, _release(version, entries, released["date"]))
    notes.data["releases"] = ([upcoming] if upcoming and upcoming["entries"] else []) + history
    if not notes.save_checked("develop"):
        return []

    lines = [f"Ported {version} ({released['date']}, {len(entries)} entries) from {ref}."]
    if upcoming:
        lines.append(
            f"Moved out of {notes.vocab.unreleased!r}: {len(moved)}; "
            f"still upcoming: {len(upcoming['entries'])}."
        )
    if kept:
        lines.append("Kept develop-only fields: " + "; ".join(kept) + ".")
    if rewritten:
        lines.append(
            f"Took the {ref} text for: {', '.join(rewritten)}. If develop has changed one of "
            f"these features since the cut, describe that in a new {notes.vocab.unreleased!r} entry."
        )
    return lines + [
        "",
        "Open a pull request to develop with it:",
        f"  git add {RELEASES_PATH}",
        f'  git commit -m "docs(whats-new): bring the v{version} release notes to develop"',
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo-root", default=".", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("cut", help='rename "next" on a new release branch')
    command.add_argument("line", help="release line, e.g. 2.4")
    command = commands.add_parser("finalize", help="date a release before its final tag")
    command.add_argument("version", help="final version, e.g. 2.4.0")
    command.add_argument(
        "--date", default=datetime.date.today().isoformat(), help="YYYY-MM-DD (default: today)"
    )
    command = commands.add_parser("port", help="bring a final release's notes to develop")
    command.add_argument("version", help="final version, e.g. 2.4.0")
    command.add_argument("--from", dest="ref", required=True, help="e.g. origin/release/v2.4")
    args = parser.parse_args()

    try:
        notes = Notes(args.repo_root.resolve())
        if args.command == "cut":
            lines = cut(notes, args.line)
        elif args.command == "finalize":
            lines = finalize(notes, args.version, args.date)
        else:
            lines = port(notes, args.version, args.ref)
    except (Abort, OSError, ValueError, KeyError) as error:
        print(f"release_notes.py {args.command}: {error}")
        return 2
    if not lines:
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
