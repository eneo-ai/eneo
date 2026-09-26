#!/usr/bin/env node
/**
 * Verifies web-next next-intl safety:
 * - generated locale catalogs hold exactly the keys and values that
 *   `bun run i18n:convert` writes (the key order is the converter's);
 * - locale catalogs do not contain duplicate top-level keys;
 * - generated locale catalogs have the same key set;
 * - web-next-only extra catalogs have the same key set;
 * - literal next-intl calls, e.g. `t("save")`, resolve in every generated
 *   locale.
 *
 * The first check is strict on purpose, which couples web-next to apps/web:
 * after apps/web/messages changes (merging develop), lint fails until someone
 * runs the converter. A changed apps/web string looks just like a hand edit
 * in messages/*, so letting upstream changes through would let hand edits
 * through too, for the next run to revert, and would miss keys apps/web
 * deletes while web-next still uses them (how ~750 keys once ended up only in
 * messages/*). Failing at the merge puts the review of apps/web's changes
 * there instead of in someone's later converter diff.
 *
 * Dynamic keys are intentionally ignored; keep those covered by focused tests
 * or a local allow-list near the owner.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import {
  appRoot,
  buildLocale,
  catalogPaths,
  diffCatalogs,
  locales,
  messagesDir,
  readCatalog
} from "./i18n-catalogs.mjs";

const srcRoot = path.join(appRoot, "src");

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const file = path.join(dir, entry);
    const stat = statSync(file);
    if (stat.isDirectory()) {
      if (entry === "messages" && file === messagesDir) continue;
      walk(file, files);
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry)) files.push(file);
  }
  return files;
}

const catalogs = Object.fromEntries(
  locales.map((locale) => {
    const file = catalogPaths(locale).messages;
    if (!existsSync(file)) throw new Error(`Missing generated locale catalog: ${file}`);
    return [locale, readCatalog(file)];
  })
);

const built = Object.fromEntries(locales.map((locale) => [locale, buildLocale(locale)]));

const LIST_LIMIT = 20;

function preview(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return JSON.stringify(text.length > 60 ? `${text.slice(0, 59)}…` : text);
}

function list(keys, describe) {
  const lines = keys.slice(0, LIST_LIMIT).map((key) => `    ${describe(key)}`);
  if (keys.length > LIST_LIMIT) lines.push(`    … and ${keys.length - LIST_LIMIT} more`);
  return lines;
}

// Everything a converter run would change in messages/*, i.e. hand edits and
// changes to its inputs that nobody has converted yet.
const driftFailures = [];

for (const locale of locales) {
  const { paths, extra, messages: expected } = built[locale];
  const current = catalogs[locale];
  const { dropped, changed, added } = diffCatalogs(current, expected);
  if (dropped.length + changed.length + added.length === 0) continue;

  const extraFile = path.relative(appRoot, paths.extra);
  const sourceFile = `apps/web/messages/${locale}.json`;
  const change = (key) => `"${key}": ${preview(current[key])} → ${preview(expected[key])}`;
  const fromExtra = changed.filter((key) => Object.hasOwn(extra, key));
  const fromSource = changed.filter((key) => !Object.hasOwn(extra, key));

  driftFailures.push(
    `${path.relative(appRoot, paths.messages)} is not what \`bun run i18n:convert\` writes:`
  );
  if (dropped.length > 0) {
    driftFailures.push(
      `  It would drop these (in neither ${sourceFile} nor ${extraFile}); move the ones web-next uses to ${extraFile}:`,
      ...list(dropped, (key) => `"${key}": ${preview(current[key])}`)
    );
  }
  if (fromExtra.length > 0) {
    driftFailures.push(
      `  It would overwrite these with ${extraFile}; put the text you want there:`,
      ...list(fromExtra, change)
    );
  }
  if (fromSource.length > 0) {
    driftFailures.push(
      `  It would overwrite these with ${sourceFile}; if you changed one here, move it to ${extraFile}:`,
      ...list(fromSource, change)
    );
  }
  if (added.length > 0) {
    const shown = added.slice(0, 8).map((key) => `"${key}"`);
    if (added.length > shown.length) shown.push("…");
    driftFailures.push(`  It would add ${added.length} key(s): ${shown.join(", ")}`);
  }
}

function compareKeyParity(label, records) {
  const [baseLocale, ...otherLocales] = locales;
  const baseKeys = new Set(Object.keys(records[baseLocale] ?? {}));
  const failures = [];

  for (const locale of otherLocales) {
    const keys = new Set(Object.keys(records[locale] ?? {}));
    for (const key of baseKeys) {
      if (!keys.has(key))
        failures.push(`${label}: "${key}" exists in ${baseLocale} but not ${locale}`);
    }
    for (const key of keys) {
      if (!baseKeys.has(key))
        failures.push(`${label}: "${key}" exists in ${locale} but not ${baseLocale}`);
    }
  }

  return failures;
}

const extraCatalogs = Object.fromEntries(locales.map((locale) => [locale, built[locale].extra]));

const parityFailures = [
  ...compareKeyParity("generated messages", catalogs),
  ...compareKeyParity("web-next extra messages", extraCatalogs)
];

const literalCallPattern = /\bt\(\s*["'`]([A-Za-z0-9_.-]+)["'`]/g;
const missing = [];

for (const file of walk(srcRoot)) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(literalCallPattern)) {
    const key = match[1];
    const missingLocales = locales.filter((locale) => !(key in catalogs[locale]));
    if (missingLocales.length > 0) {
      missing.push({
        file: path.relative(appRoot, file),
        key,
        locales: missingLocales
      });
    }
  }
}

if (driftFailures.length > 0 || parityFailures.length > 0 || missing.length > 0) {
  if (driftFailures.length > 0) {
    console.error("web-next i18n catalogs are out of date:");
    for (const failure of driftFailures) console.error(`  ${failure}`);
    console.error(
      "\nsrc/lib/i18n/messages/* is generated; web-next's strings live in " +
        "src/lib/i18n/extra/{sv,en}.json (same keys in both). Then run `bun run i18n:convert`.\n"
    );
  }

  if (parityFailures.length > 0) {
    console.error("web-next i18n locale parity failed:");
    for (const failure of parityFailures) console.error(`  ${failure}`);
    console.error("");
  }

  if (missing.length > 0) {
    console.error("Missing web-next i18n keys for literal t(...) calls:");
    for (const item of missing) {
      console.error(`  ${item.file}: "${item.key}" missing in ${item.locales.join(", ")}`);
    }
    console.error(
      "\nAdd web-next-only strings to src/lib/i18n/extra/{sv,en}.json and run " +
        "`bun run i18n:convert`."
    );
  }
  process.exit(1);
}

console.log("web-next i18n keys OK");
