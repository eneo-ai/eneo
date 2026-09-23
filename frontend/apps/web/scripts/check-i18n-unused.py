#!/usr/bin/env python3
"""Fail when a message key in messages/en.json is not referenced by the web app.

Unused keys still get translated and reviewed, and they hide which texts the UI
actually shows. A key counts as used when its name appears as a whole word in
any source file under src/, tests/ or e2e/ (the generated paraglide output is
skipped). Keys are only ever referenced by their full name (`m.some_key()` or a
literal passed to a lookup helper), so a plain word search is exact enough.
"""

import json
import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).parent.parent
MESSAGES = APP_ROOT / "messages" / "en.json"
SOURCE_ROOTS = ("src", "tests", "e2e")
SOURCE_SUFFIXES = {".ts", ".js", ".mjs", ".svelte"}
WORD = re.compile(r"[A-Za-z0-9_]+")


def referenced_words() -> set[str]:
    words: set[str] = set()
    for root in SOURCE_ROOTS:
        base = APP_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and "paraglide" not in path.parts and path.is_file():
                words.update(WORD.findall(path.read_text(errors="ignore")))
    return words


def main() -> int:
    keys = [key for key in json.loads(MESSAGES.read_text()) if not key.startswith("$")]
    words = referenced_words()
    unused = [key for key in keys if key not in words]
    if unused:
        print(f"\n❌ {len(unused)} message key(s) in messages/en.json are not used by the web app:")
        for key in unused:
            print(f'   - "{key}"')
        print("\nRemove them from messages/en.json and messages/sv.json.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
