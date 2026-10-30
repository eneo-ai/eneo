#!/usr/bin/env bash
# Move reusable modules/styles out of Next, preserving git renames and import targets.
# Frozen login/activate, the server-env public wrapper and the superseded Next
# integrations view stay in src/app until P6B. Their Vite owners already exist.
set -euo pipefail
cd "$(dirname "$0")/../.."
node --input-type=module <<'JS'
import { existsSync, readFileSync, readdirSync, mkdirSync, writeFileSync, statSync } from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

// Left is relative to src/app; right is relative to src. Keep this single-file
// transform usable before a merge and safe to repeat after it.
const table = `
(app)/account/appearance/account-appearance.client.tsx|features/account/account-appearance.tsx
(app)/account/appearance/account-appearance.test.tsx|features/account/account-appearance.test.tsx
(app)/admin/admin-page-bar.client.tsx|features/admin/admin-page-bar.tsx
(app)/admin/admin-page-bar.test.tsx|features/admin/admin-page-bar.test.tsx
(app)/dashboard/catalog.ts|features/dashboard/catalog.ts
(app)/dashboard/catalog.test.ts|features/dashboard/catalog.test.ts
(app)/dashboard/queries.ts|features/dashboard/queries.ts
(app)/dashboard/dashboard-list.client.tsx|features/dashboard/dashboard-list.client.tsx
(app)/dashboard/dashboard-list.test.tsx|features/dashboard/dashboard-list.test.tsx
(app)/dashboard/[assistantId]/[[...sessionId]]/dashboard-chat.client.tsx|features/dashboard/dashboard-chat.client.tsx
(app)/dashboard/[assistantId]/[[...sessionId]]/dashboard-chat.test.tsx|features/dashboard/dashboard-chat.test.tsx
(app)/dashboard/app/[appId]/dashboard-app.client.tsx|features/dashboard/dashboard-app.client.tsx
(app)/spaces/[spaceId]/chat/space-chat.client.tsx|features/spaces/chat/space-chat.client.tsx
(app)/spaces/[spaceId]/chat/space-chat.test.tsx|features/spaces/chat/space-chat.test.tsx
(app)/spaces/[spaceId]/overview/space-overview.client.tsx|features/spaces/overview/space-overview.client.tsx
(app)/spaces/[spaceId]/knowledge/collections/[collectionId]/collection-detail.client.tsx|features/knowledge/detail/collection-detail.client.tsx
(app)/spaces/[spaceId]/knowledge/collections/[collectionId]/collection-detail.test.tsx|features/knowledge/detail/collection-detail.test.tsx
(app)/spaces/[spaceId]/knowledge/websites/[websiteId]/website-detail.client.tsx|features/knowledge/detail/website-detail.client.tsx
(app)/spaces/[spaceId]/knowledge/websites/[websiteId]/website-detail.test.tsx|features/knowledge/detail/website-detail.test.tsx
(app)/spaces/[spaceId]/knowledge/integrations/[integrationKnowledgeId]/item-detail.client.tsx|features/knowledge/integrations/item-detail.client.tsx
(app)/spaces/[spaceId]/knowledge/integrations/[integrationKnowledgeId]/item-detail.test.tsx|features/knowledge/integrations/item-detail.test.tsx
(app)/spaces/[spaceId]/knowledge/integrations/wrapper/[wrapperId]/wrapper-detail.client.tsx|features/knowledge/integrations/wrapper-detail.client.tsx
(app)/spaces/[spaceId]/knowledge/integrations/wrapper/[wrapperId]/wrapper-detail.test.tsx|features/knowledge/integrations/wrapper-detail.test.tsx
globals.css|styles/globals.css
globals-css.test.ts|styles/globals-css.test.ts
globals-forced-colors.test.tsx|styles/globals-forced-colors.test.tsx
`
  .trim()
  .split("\n")
  .map((line) => line.split("|"));
const root = process.cwd();
const src = path.join(root, "src");
const app = path.join(src, "app");
const moves = new Map(table.map(([old, target]) => [path.join(app, old), path.join(src, target)]));
const pending = [];
for (const [old, target] of moves) {
  if (existsSync(old) && existsSync(target))
    throw new Error(`Both source and target exist: ${old} -> ${target}`);
  if (existsSync(old)) pending.push([old, target]);
  else if (!existsSync(target)) throw new Error(`Missing source and target: ${old} -> ${target}`);
}
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(file) : [file];
  });
}
const sources = [...walk(src), ...walk(path.join(root, "tests"))].filter((file) =>
  /\.(?:ts|tsx|css)$/.test(file)
);
const allowedActions = new Set(["(public)/login/actions.ts", "(public)/activate/actions.ts"]);
for (const file of sources) {
  if (
    file.startsWith(app + path.sep) &&
    /^['"]use server['"];?/m.test(readFileSync(file, "utf8")) &&
    !allowedActions.has(path.relative(app, file))
  ) {
    throw new Error(`Unexpected Server Action under src/app: ${file}`);
  }
}
function resolve(specifier, file) {
  const base = specifier.startsWith("@/")
    ? path.join(src, specifier.slice(2))
    : path.resolve(path.dirname(file), specifier);
  return [
    base,
    base + ".ts",
    base + ".tsx",
    base + ".css",
    path.join(base, "index.ts"),
    path.join(base, "index.tsx")
  ].find((file) => moves.has(file) || (existsSync(file) && statSync(file).isFile()));
}
function rewriteSpecifier(specifier, file, moved) {
  if (!specifier.startsWith(".") && !specifier.startsWith("@/")) return specifier;
  const target = resolve(specifier, file);
  if (!target) {
    if (moved && specifier.startsWith("."))
      throw new Error(`Cannot resolve ${specifier} from ${file}`);
    return specifier;
  }
  if (
    moved &&
    specifier.startsWith(".") &&
    target.startsWith(app + path.sep) &&
    !moves.has(target)
  ) {
    throw new Error(`Moved module imports an unmoved Next module: ${file} -> ${target}`);
  }
  if (!moves.has(target) && !(moved && specifier.startsWith("."))) return specifier;
  const destination = moves.get(target) ?? target;
  if (!destination.startsWith(src + path.sep))
    throw new Error(`Import target is outside src: ${destination}`);
  return "@/" + path.relative(src, destination).replace(/\.(?:ts|tsx)$/, "");
}
const importPattern =
  /\b(from\s+|import\s*(?:\(\s*)?|vi\.(?:mock|doMock|unmock)\s*\(\s*)(['"])([^'"\n]+)\2/g;
const updates = new Map();
for (const file of [
  ...sources,
  ...["components.json", "AGENTS.md", "README.md", "ACCESSIBILITY.md"].map((file) =>
    path.join(root, file)
  )
]) {
  const original = readFileSync(file, "utf8");
  const moved = moves.has(file);
  let content = original;
  if (/\.tsx?$/.test(file)) {
    content = content.replace(
      importPattern,
      (_, prefix, quote, specifier) =>
        prefix + quote + rewriteSpecifier(specifier, file, moved) + quote
    );
    if (moved) {
      // Reuse the established React seams. Next route files keep their server APIs.
      for (const [from, to] of [
        ["next-intl", "use-intl"],
        ["next/navigation", "@/lib/navigation"],
        ["next/link", "@/lib/link"]
      ]) {
        for (const quote of ['"', "'"])
          content = content.replaceAll(quote + from + quote, quote + to + quote);
      }
      content = content.replaceAll("NextIntlClientProvider", "IntlProvider");
    }
  }
  content = content
    .replaceAll("src/app/globals", "src/styles/globals")
    .replaceAll("../app/globals.css", "../styles/globals.css");
  if (content !== original) updates.set(moves.get(file) ?? file, content);
}
// Validate every move/import before changing the working tree; a conflict or
// frozen relative dependency must not leave a half-applied move table.
for (const [old, target] of pending) {
  mkdirSync(path.dirname(target), { recursive: true });
  execFileSync("git", ["mv", "--", old, target], { stdio: "inherit" });
}
for (const [file, content] of updates) writeFileSync(file, content);
console.log(`Moved ${pending.length} files; updated ${updates.size} import/reference files.`);
JS
