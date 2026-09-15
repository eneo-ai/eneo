#!/usr/bin/env python3
"""Validate the user-facing release notes in frontend/packages/whats-new.

The JSON schema next to releases.json documents the shape; this script is the
CI backstop (stdlib only, no jsonschema dependency) and also enforces what a
schema cannot express:

  * releases are ordered newest first with unique versions
  * entry ids are unique within a release
  * texts are user-facing: no PR/issue numbers, GitHub URLs, code-like tokens
  * every showMe anchor exists as data-tour="..." in the web app

Run locally:  python3 scripts/check_whats_new.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RELEASES_PATH = Path("frontend/packages/whats-new/releases.json")
WEB_SRC = Path("frontend/apps/web/src")

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HREF_RE = re.compile(r"^/[^\s]*$")

LOCALES = ("en", "sv")
TYPES = {"new", "improved", "fixed"}
AREAS = {
    "chat",
    "assistants",
    "knowledge",
    "spaces",
    "skills",
    "account",
    "admin",
    "platform",
}
AUDIENCES = {"all", "admin"}
TITLE_MAX = 60

# Things that mark a text as written for developers rather than users.
INTERNAL_TOKENS = [
    (re.compile(r"(?<![\w/])#\d+\b"), "issue/PR number"),
    (re.compile(r"github\.com/", re.IGNORECASE), "GitHub URL"),
    (re.compile(r"`"), "code formatting"),
    (re.compile(r"\b(?:/api/v\d|PATCH|POST|DELETE)\b"), "API endpoint"),
    (re.compile(r"\b\w+\.(?:py|ts|svelte|tsx|js)\b"), "file name"),
    (re.compile(r"\b[a-z]+_[a-z_]+\b"), "snake_case identifier"),
]


class Problem(Exception):
    pass


def _semver_key(version: str) -> tuple[int, int, int, int, str]:
    match = VERSION_RE.match(version)
    assert match is not None
    major, minor, patch, pre = match.groups()
    # A pre-release sorts before its final release.
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def _require_localized(value: object, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: must be an object with 'en' and 'sv'")
        return
    for locale in LOCALES:
        text = value.get(locale)
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}.{locale}: missing or empty")
            continue
        for pattern, label in INTERNAL_TOKENS:
            found = pattern.search(text)
            if found:
                errors.append(
                    f"{where}.{locale}: contains {label} ({found.group(0)!r}); "
                    "write it the way a user would read it"
                )
    extra = set(value) - set(LOCALES)
    if extra:
        errors.append(f"{where}: unexpected locales {sorted(extra)}")


def _check_entry(entry: object, where: str, errors: list[str]) -> str | None:
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be an object")
        return None

    allowed = {"id", "type", "area", "audience", "title", "body", "showMe"}
    extra = set(entry) - allowed
    if extra:
        errors.append(f"{where}: unexpected keys {sorted(extra)}")

    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not ID_RE.match(entry_id):
        errors.append(f"{where}.id: must be kebab-case")
        entry_id = None

    if entry.get("type") not in TYPES:
        errors.append(f"{where}.type: must be one of {sorted(TYPES)}")
    if entry.get("area") not in AREAS:
        errors.append(f"{where}.area: must be one of {sorted(AREAS)}")
    if "audience" in entry and entry["audience"] not in AUDIENCES:
        errors.append(f"{where}.audience: must be one of {sorted(AUDIENCES)}")

    _require_localized(entry.get("title"), f"{where}.title", errors)
    _require_localized(entry.get("body"), f"{where}.body", errors)
    title = entry.get("title")
    if isinstance(title, dict):
        for locale in LOCALES:
            text = title.get(locale)
            if isinstance(text, str) and len(text) > TITLE_MAX:
                errors.append(
                    f"{where}.title.{locale}: {len(text)} characters, max {TITLE_MAX}"
                )

    show_me = entry.get("showMe")
    if show_me is not None:
        if not isinstance(show_me, dict) or set(show_me) != {"href", "anchor"}:
            errors.append(f"{where}.showMe: must have exactly 'href' and 'anchor'")
        else:
            if not isinstance(show_me["href"], str) or not HREF_RE.match(
                show_me["href"]
            ):
                errors.append(f"{where}.showMe.href: must be an app path like /account")
            if not isinstance(show_me["anchor"], str) or not ID_RE.match(
                show_me["anchor"]
            ):
                errors.append(f"{where}.showMe.anchor: must be kebab-case")

    return entry_id


def _collect_anchors(web_src: Path) -> set[str]:
    anchors: set[str] = set()
    pattern = re.compile(r"""data-tour=["']([a-z0-9-]+)["']""")
    if not web_src.is_dir():
        return anchors
    for path in web_src.rglob("*.svelte"):
        anchors.update(pattern.findall(path.read_text(encoding="utf-8")))
    return anchors


def validate(data: object, anchors: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["top level must be an object"]
    extra = set(data) - {"$schema", "releases"}
    if extra:
        errors.append(f"top level: unexpected keys {sorted(extra)}")
    releases = data.get("releases")
    if not isinstance(releases, list):
        return errors + ["releases: must be an array"]

    seen_versions: list[str] = []
    for index, release in enumerate(releases):
        where = f"releases[{index}]"
        if not isinstance(release, dict):
            errors.append(f"{where}: must be an object")
            continue
        extra = set(release) - {"version", "date", "entries"}
        if extra:
            errors.append(f"{where}: unexpected keys {sorted(extra)}")

        version = release.get("version")
        if not isinstance(version, str) or not VERSION_RE.match(version):
            errors.append(f"{where}.version: must be semver without a leading v")
            version = None
        elif version in seen_versions:
            errors.append(f"{where}.version: {version} appears more than once")
        elif seen_versions and _semver_key(seen_versions[-1]) <= _semver_key(version):
            errors.append(
                f"{where}.version: {version} must come after {seen_versions[-1]} "
                "(newest release first)"
            )
        if version:
            seen_versions.append(version)
            where = f"release {version}"

        date = release.get("date")
        if date is not None and (not isinstance(date, str) or not DATE_RE.match(date)):
            errors.append(f"{where}.date: must be YYYY-MM-DD")

        entries = release.get("entries")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{where}.entries: must be a non-empty array")
            continue
        ids: set[str] = set()
        for entry_index, entry in enumerate(entries):
            entry_where = f"{where}.entries[{entry_index}]"
            entry_id = _check_entry(entry, entry_where, errors)
            if entry_id is None:
                continue
            if entry_id in ids:
                errors.append(f"{entry_where}.id: {entry_id!r} is not unique in the release")
            ids.add(entry_id)
            show_me = entry.get("showMe") if isinstance(entry, dict) else None
            if isinstance(show_me, dict):
                anchor = show_me.get("anchor")
                if isinstance(anchor, str) and anchor not in anchors:
                    errors.append(
                        f"{entry_where}.showMe.anchor: no element with "
                        f'data-tour="{anchor}" in {WEB_SRC}'
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()
    root: Path = args.repo_root.resolve()

    releases_path = root / RELEASES_PATH
    try:
        data = json.loads(releases_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"{RELEASES_PATH}: not found")
        return 1
    except json.JSONDecodeError as error:
        print(f"{RELEASES_PATH}: invalid JSON: {error}")
        return 1

    errors = validate(data, _collect_anchors(root / WEB_SRC))
    if errors:
        print(f"{RELEASES_PATH}: {len(errors)} problem(s)")
        for error in errors:
            print(f"  - {error}")
        print("See frontend/packages/whats-new/PLAYBOOK.md for the rules.")
        return 1

    count = sum(len(r["entries"]) for r in data["releases"])
    print(f"{RELEASES_PATH}: OK ({len(data['releases'])} release(s), {count} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
