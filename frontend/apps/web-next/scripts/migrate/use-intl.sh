#!/usr/bin/env bash
# Move client imports and mocks to use-intl. Next server imports stay until route removal.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
from pathlib import Path
import subprocess

files = subprocess.check_output(["rg", "--files", "src", "-g", "*.ts", "-g", "*.tsx", "-g", "!src/app/**"], text=True).splitlines()
skip = {"src/test/render.tsx", "src/components/composites/loading-state.tsx"}
changed = 0
for name in files:
    if name in skip:
        continue
    path = Path(name)
    before = path.read_text()
    after = before.replace('"next-intl"', '"use-intl"').replace('NextIntlClientProvider', 'IntlProvider')
    if after != before:
        path.write_text(after)
        changed += 1
print(f"use-intl: updated {changed} files")
PY
