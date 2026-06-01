#!/usr/bin/env python3
"""Pre-commit hook: detect duplicate keys in i18n message JSON files.

JSON silently accepts duplicate keys (last value wins), which means
translations can be accidentally overwritten without any warning.
This script exits with code 1 if any duplicates are found.
"""

import collections
import sys
from pathlib import Path

MESSAGES_DIR = Path(__file__).parent.parent / "messages"


def find_duplicate_keys(filepath: Path) -> list[str]:
    keys: list[str] = []
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('"') and '":' in stripped:
                key = stripped.split('"')[1]
                keys.append(key)
    return [k for k, v in collections.Counter(keys).items() if v > 1]


def main() -> int:
    errors = 0
    for json_file in sorted(MESSAGES_DIR.glob("*.json")):
        dupes = find_duplicate_keys(json_file)
        if dupes:
            errors += 1
            print(f"\n❌ {json_file.name} has {len(dupes)} duplicate key(s):")
            for key in dupes:
                print(f"   - \"{key}\"")

    if errors:
        print(f"\nRemove duplicates before committing. Keep one definition per key.\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
