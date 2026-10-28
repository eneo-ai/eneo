#!/usr/bin/env bash
# next/navigation hooks and next/link -> the app's navigation seam, outside src/app:
#   import { useRouter, usePathname, useSearchParams } from "next/navigation" -> "@/lib/navigation"
#   import Link from "next/link" -> "@/lib/link"; vi.mock(...) and import("next/link") likewise.
# Idempotent. Plan: .codex/plans/web-next-vite-migration-plan.md §3.2, §4 (fas 3).
# Usage (from frontend/apps/web-next): bash scripts/migrate/navigation-seam.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
# src/app keeps Next until it is ported (fas 5). The other files are edited by
# hand in the PR that adds this script; on other branches the merge brings them.
skip=(
  --glob '!src/app/**'
  --glob '!src/lib/navigation.ts' --glob '!src/lib/link.ts'
  --glob '!src/lib/navigation.test.ts'
  --glob '!src/test/navigation.ts' --glob '!src/test/render.tsx'
  --glob '!src/features/spaces/frame/space-frame.tsx'
  --glob '!src/features/spaces/frame/space-frame.test.tsx'
)
hook='(useRouter|usePathname|useSearchParams)'
{ rg -l "${skip[@]}" -e '"next/navigation"' -e '"next/link"' src || true; } |
  while IFS= read -r file; do
    sed -i.bak -E \
      -e "s#^import \\{ ($hook(, $hook)*) \\} from \"next/navigation\";\$#import { \\1 } from \"@/lib/navigation\";#" \
      -e 's#^import Link from "next/link";$#import Link from "@/lib/link";#' \
      -e 's#vi\.mock\("next/navigation"#vi.mock("@/lib/navigation"#g' \
      -e 's#vi\.mock\("next/link"#vi.mock("@/lib/link"#g' \
      -e 's#import\("next/link"\)#import("@/lib/link")#g' \
      "$file"
    rm -f "$file.bak"
  done
# May stay: server-only redirect/unstable_rethrow (deleted with 2e/6B).
left=$( { rg -n "${skip[@]}" -e '"next/navigation"' -e '"next/link"' src || true; } |
  { grep -Ev 'import \{ (redirect|unstable_rethrow) \} from "next/navigation";' || true; } )
if [[ -n "$left" ]]; then
  printf 'navigation-seam: not rewritten (extend the script, do not hand-edit):\n%s\n' "$left" >&2
  exit 1
fi
