#!/usr/bin/env python3
"""Validate the user-facing release notes in frontend/packages/whats-new.

releases.schema.json is the single source for the shape and the closed
vocabularies (entry types, areas, audiences, locales, id/version patterns);
this script reads them from there so a vocabulary change is one edit. It is
the CI backstop (stdlib only, no jsonschema dependency) and also enforces what
a schema cannot express:

  * releases are ordered newest first with unique versions
  * entry ids are unique within a release
  * texts are user-facing: no PR/issue numbers, GitHub URLs, code-like tokens
  * every showMe href resolves to a page under the web app's (app) routes
  * every showMe anchor exists as data-tour="..." in the web app

With --release-tag vX.Y.Z (the image build runs this on every tag) it also
checks that the newest entry fits the release being built: it may not be
newer than the tag (notes for a future version leaking into an older release
branch), a final tag whose version has an entry must carry a date (no
"Upcoming" in production), and a hotfix without user-facing changes needs no
entry at all.

Run locally:  python3 scripts/check_whats_new.py [--release-tag v2.2.0]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RELEASES_PATH = Path("frontend/packages/whats-new/releases.json")
SCHEMA_PATH = Path("frontend/packages/whats-new/releases.schema.json")
WEB_SRC = Path("frontend/apps/web/src")
APP_ROUTES = WEB_SRC / "routes" / "(app)"

TITLE_MAX = 60
VERSION_RE_LOOSE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class Vocabulary:
    """The parts of releases.schema.json this script enforces."""

    def __init__(self, schema: dict) -> None:
        defs = schema["$defs"]
        entry = defs["entry"]["properties"]
        show_me = entry["showMe"]["properties"]
        self.locales: tuple[str, ...] = tuple(defs["localized"]["required"])
        self.types: set[str] = set(entry["type"]["enum"])
        self.areas: set[str] = set(entry["area"]["enum"])
        self.audiences: set[str] = set(entry["audience"]["enum"])
        self.entry_keys: set[str] = set(entry)
        self.release_keys: set[str] = set(defs["release"]["properties"])
        self.version_re = re.compile(defs["release"]["properties"]["version"]["pattern"])
        self.date_re = re.compile(defs["release"]["properties"]["date"]["pattern"])
        self.id_re = re.compile(entry["id"]["pattern"])
        self.href_re = re.compile(show_me["href"]["pattern"])
        self.anchor_re = re.compile(show_me["anchor"]["pattern"])


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


def _semver_key(version: str) -> tuple[int, int, int, int, tuple[tuple[int, object], ...]]:
    core, _, pre = version.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    # A pre-release sorts before its final release; numeric identifiers sort
    # numerically, text ones after them (SemVer §11).
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in pre.split(".") if part
    )
    return (major, minor, patch, 0 if identifiers else 1, identifiers)


def _require_localized(
    value: object, where: str, errors: list[str], vocab: Vocabulary
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: must be an object with {', '.join(vocab.locales)}")
        return
    for locale in vocab.locales:
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
    extra = set(value) - set(vocab.locales)
    if extra:
        errors.append(f"{where}: unexpected locales {sorted(extra)}")


def _check_entry(
    entry: object, where: str, errors: list[str], vocab: Vocabulary
) -> str | None:
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be an object")
        return None

    extra = set(entry) - vocab.entry_keys
    if extra:
        errors.append(f"{where}: unexpected keys {sorted(extra)}")

    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not vocab.id_re.match(entry_id):
        errors.append(f"{where}.id: must be kebab-case")
        entry_id = None

    if entry.get("type") not in vocab.types:
        errors.append(f"{where}.type: must be one of {sorted(vocab.types)}")
    if entry.get("area") not in vocab.areas:
        errors.append(f"{where}.area: must be one of {sorted(vocab.areas)}")
    if "audience" in entry and entry["audience"] not in vocab.audiences:
        errors.append(f"{where}.audience: must be one of {sorted(vocab.audiences)}")

    _require_localized(entry.get("title"), f"{where}.title", errors, vocab)
    _require_localized(entry.get("body"), f"{where}.body", errors, vocab)
    title = entry.get("title")
    if isinstance(title, dict):
        for locale in vocab.locales:
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
            if not isinstance(show_me["href"], str) or not vocab.href_re.match(
                show_me["href"]
            ):
                errors.append(f"{where}.showMe.href: must be an app path like /account")
            if not isinstance(show_me["anchor"], str) or not vocab.anchor_re.match(
                show_me["anchor"]
            ):
                errors.append(f"{where}.showMe.anchor: must be kebab-case")

    return entry_id


def _route_exists(href: str, app_routes: Path) -> bool:
    """True when href matches a +page.svelte under routes/(app), honouring
    [param] and [[optional]] segments and route groups in parentheses."""
    path = href.split("?", 1)[0].split("#", 1)[0].strip("/")
    wanted = [segment for segment in path.split("/") if segment]
    if not app_routes.is_dir():
        return True
    for page in app_routes.rglob("+page.svelte"):
        segments = [
            part
            for part in page.parent.relative_to(app_routes).parts
            if not (part.startswith("(") and part.endswith(")"))
        ]
        if _segments_match(segments, wanted):
            return True
    return False


def _segments_match(pattern: list[str], wanted: list[str]) -> bool:
    if not pattern:
        return not wanted
    head, rest = pattern[0], pattern[1:]
    if head.startswith("[[") and head.endswith("]]"):
        return _segments_match(rest, wanted) or (
            bool(wanted) and _segments_match(rest, wanted[1:])
        )
    if not wanted:
        return False
    if head.startswith("[") and head.endswith("]"):
        return _segments_match(rest, wanted[1:])
    return head == wanted[0] and _segments_match(rest, wanted[1:])


def _collect_anchors(web_src: Path) -> set[str]:
    """Literal data-tour attributes plus the `tour` prop that Page.Title
    renders as one."""
    anchors: set[str] = set()
    pattern = re.compile(r"""\b(?:data-tour|tour)=["']([a-z0-9-]+)["']""")
    if not web_src.is_dir():
        return anchors
    for path in web_src.rglob("*.svelte"):
        anchors.update(pattern.findall(path.read_text(encoding="utf-8")))
    return anchors


def validate(
    data: object, vocab: Vocabulary, anchors: set[str], app_routes: Path
) -> list[str]:
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
        extra = set(release) - vocab.release_keys
        if extra:
            errors.append(f"{where}: unexpected keys {sorted(extra)}")

        version = release.get("version")
        if not isinstance(version, str) or not vocab.version_re.match(version):
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
        if date is not None and (
            not isinstance(date, str) or not vocab.date_re.match(date)
        ):
            errors.append(f"{where}.date: must be YYYY-MM-DD")

        entries = release.get("entries")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{where}.entries: must be a non-empty array")
            continue
        ids: set[str] = set()
        for entry_index, entry in enumerate(entries):
            entry_where = f"{where}.entries[{entry_index}]"
            entry_id = _check_entry(entry, entry_where, errors, vocab)
            if entry_id is None:
                continue
            if entry_id in ids:
                errors.append(f"{entry_where}.id: {entry_id!r} is not unique in the release")
            ids.add(entry_id)
            show_me = entry.get("showMe") if isinstance(entry, dict) else None
            if isinstance(show_me, dict):
                href = show_me.get("href")
                if isinstance(href, str) and not _route_exists(href, app_routes):
                    errors.append(
                        f"{entry_where}.showMe.href: no page at {href} under "
                        f"{APP_ROUTES}; remove showMe or point it at a page that exists"
                    )
                anchor = show_me.get("anchor")
                if isinstance(anchor, str) and anchor not in anchors:
                    errors.append(
                        f"{entry_where}.showMe.anchor: no element with "
                        f'data-tour="{anchor}" in {WEB_SRC}; remove showMe or '
                        "restore the attribute"
                    )
    return errors


def _core_version(version: str) -> str:
    return version.partition("-")[0]


def check_release_tag(data: dict, tag: str) -> list[str]:
    """Rules for the release identified by a git tag (``v2.2.0``, ``v2.2.0-rc.1``)."""
    version = tag.removeprefix("v")
    if not VERSION_RE_LOOSE.match(version):
        return [f"release tag {tag!r} is not vMAJOR.MINOR.PATCH[-prerelease]"]
    releases = data.get("releases") or []
    if not releases:
        return []
    newest = releases[0]
    newest_version = newest.get("version")
    if not isinstance(newest_version, str):
        return []
    if _semver_key(_core_version(newest_version)) > _semver_key(_core_version(version)):
        return [
            f"newest entry {newest_version} is newer than release tag {tag}; "
            "release notes for a later version must not ship in this release"
        ]
    is_final = "-" not in version
    if is_final and _core_version(newest_version) == version and not newest.get("date"):
        return [
            f"entry {newest_version} has no date but {tag} is a final release; "
            'set "date" before tagging so the app does not show it as upcoming'
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument(
        "--release-tag",
        help="git tag being built (vX.Y.Z or vX.Y.Z-rc.N); adds the release rules",
    )
    args = parser.parse_args()
    root: Path = args.repo_root.resolve()

    loaded: dict[Path, object] = {}
    for path in (SCHEMA_PATH, RELEASES_PATH):
        try:
            loaded[path] = json.loads((root / path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"{path}: not found")
            return 1
        except json.JSONDecodeError as error:
            print(f"{path}: invalid JSON: {error}")
            return 1
    try:
        vocab = Vocabulary(loaded[SCHEMA_PATH])  # type: ignore[arg-type]
    except (KeyError, TypeError) as error:
        print(f"{SCHEMA_PATH}: missing a definition this check relies on: {error}")
        return 1
    data = loaded[RELEASES_PATH]

    errors = validate(data, vocab, _collect_anchors(root / WEB_SRC), root / APP_ROUTES)
    if not errors and args.release_tag and isinstance(data, dict):
        errors = check_release_tag(data, args.release_tag)
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
