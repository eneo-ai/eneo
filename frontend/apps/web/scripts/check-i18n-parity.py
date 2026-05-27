#!/usr/bin/env python3
"""Pre-commit hook: ensure every i18n locale defines the same set of keys.

A key present in one locale but missing in another means users on the missing
locale silently fall back to another language for that string. This script
exits with code 1 if the locale files under messages/ diverge in their keys.
"""

import json
import sys
from pathlib import Path

MESSAGES_DIR = Path(__file__).parent.parent / "messages"
META_KEYS = {"$schema"}


def load_keys(filepath: Path) -> set[str]:
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    return set(data) - META_KEYS


def main() -> int:
    files = sorted(MESSAGES_DIR.glob("*.json"))
    if len(files) < 2:
        return 0

    keys_by_file = {f: load_keys(f) for f in files}
    union = set().union(*keys_by_file.values())

    errors = 0
    for f, keys in keys_by_file.items():
        missing = union - keys
        if missing:
            errors += 1
            print(f"\n❌ {f.name} is missing {len(missing)} key(s) defined in other locales:")
            for key in sorted(missing):
                print(f'   - "{key}"')

    if errors:
        print(
            "\nEvery locale must define the same keys. Add the missing "
            "translations (or remove the key everywhere) before committing.\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
