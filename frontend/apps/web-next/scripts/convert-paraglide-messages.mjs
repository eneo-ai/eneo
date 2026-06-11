#!/usr/bin/env node
/**
 * Converts the Paraglide (inlang message format) catalogs of apps/web into
 * next-intl catalogs for apps/web-next.
 *
 * Paraglide stores flat key → string maps with `{param}` interpolation, which
 * is already valid ICU for the simple cases. Messages that need manual review
 * are flagged on stdout and copied through unchanged:
 *   - non-string values (Paraglide variants/plurals)
 *   - keys containing "." (next-intl treats dots as namespace separators)
 *   - apostrophes directly before "{" or "}" (ICU escape semantics differ)
 *
 * Usage: node scripts/convert-paraglide-messages.mjs
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceDir = path.resolve(here, "..", "..", "web", "messages");
const targetDir = path.resolve(here, "..", "src", "lib", "i18n", "messages");
const locales = ["sv", "en"];

mkdirSync(targetDir, { recursive: true });

for (const locale of locales) {
  const sourcePath = path.join(sourceDir, `${locale}.json`);
  const source = JSON.parse(readFileSync(sourcePath, "utf8"));
  const out = {};
  const flagged = [];

  for (const [key, value] of Object.entries(source)) {
    if (key === "$schema") continue;

    if (typeof value !== "string") {
      flagged.push(`${key}: non-string value (Paraglide variant/plural), copied as-is`);
      out[key] = value;
      continue;
    }
    if (key.includes(".")) {
      flagged.push(`${key}: key contains "." (next-intl namespace separator)`);
    }
    if (/'[{}]/.test(value)) {
      flagged.push(`${key}: apostrophe before "{" or "}" (ICU escape, needs '' doubling)`);
    }
    out[key] = value;
  }

  writeFileSync(path.join(targetDir, `${locale}.json`), JSON.stringify(out, null, 2) + "\n");
  console.log(`${locale}: ${Object.keys(out).length} messages written`);
  if (flagged.length > 0) {
    console.log(`${locale}: ${flagged.length} message(s) need manual review:`);
    for (const entry of flagged) console.log(`  - ${entry}`);
  }
}
