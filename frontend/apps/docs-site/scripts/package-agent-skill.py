#!/usr/bin/env python3
"""Build the downloadable Eneo Flows Agent Skill reproducibly."""

from __future__ import annotations

import argparse
import io
import stat
import sys
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = "eneo-flows-api"
SKILL_DIR = APP_DIR / "skills" / SKILL_NAME
PACKAGE_PATH = APP_DIR / "public" / "skills" / f"{SKILL_NAME}.skill"


def build_package() -> bytes:
    if not (SKILL_DIR / "SKILL.md").is_file():
        raise FileNotFoundError(f"Missing skill entrypoint: {SKILL_DIR / 'SKILL.md'}")

    files = sorted(
        path
        for path in SKILL_DIR.rglob("*")
        if path.is_file()
        and not any(
            part.startswith(".") for part in path.relative_to(SKILL_DIR).parts
        )
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            relative_path = path.relative_to(SKILL_DIR).as_posix()
            info = zipfile.ZipInfo(
                filename=f"{SKILL_NAME}/{relative_path}",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the published package does not match its sources",
    )
    args = parser.parse_args()
    expected = build_package()

    if args.check:
        if not PACKAGE_PATH.is_file() or PACKAGE_PATH.read_bytes() != expected:
            print(
                "eneo-flows-api.skill is missing or stale; "
                "run: bun run build:skill",
                file=sys.stderr,
            )
            return 1
        print("eneo-flows-api.skill matches its sources")
        return 0

    PACKAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PACKAGE_PATH.write_bytes(expected)
    print(f"wrote {PACKAGE_PATH.relative_to(APP_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
