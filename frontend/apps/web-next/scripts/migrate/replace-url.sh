#!/usr/bin/env bash
# Route silent URL updates through the app navigation seam. Run after
# navigation-seam.sh; repeat runs make no further changes (migration phase 3).
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 - <<'PY'
from pathlib import Path
import re
import subprocess

skip = ["--glob", "!**/*.test.*", "--glob", "!src/test/**", "--glob", "!src/lib/navigation.ts"]
pattern = r'window\.history\.replaceState\(null, "", '
found = subprocess.run(["rg", "-l", *skip, pattern, "src"], capture_output=True, text=True)
if found.returncode not in (0, 1):
    raise SystemExit(found.stderr)
seam_import = re.compile(r'import\s*\{([^}]*)\}\s*from "@/lib/navigation";')
for name in found.stdout.splitlines():
    path = Path(name)
    source = path.read_text()
    source = re.sub(pattern + r'(.+)\);', r'replaceUrl(\1);', source)
    match = seam_import.search(source)
    if match:
        names = match.group(1).strip().rstrip(",")
        if not re.search(r'\breplaceUrl\b', names):
            source = source[:match.start()] + 'import { ' + names + ', replaceUrl } from "@/lib/navigation";' + source[match.end():]
    else:
        source = re.sub(r'^import ', 'import { replaceUrl } from "@/lib/navigation";\nimport ', source, count=1, flags=re.MULTILINE)
    path.write_text(source)

left = subprocess.run(["rg", "-n", *skip, pattern, "src"], capture_output=True, text=True)
if left.returncode != 1:
    raise SystemExit("replace-url: calls not rewritten (extend the transform):\n" + left.stdout + left.stderr)
PY
