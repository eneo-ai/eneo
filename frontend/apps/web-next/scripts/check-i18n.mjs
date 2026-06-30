#!/usr/bin/env node
/**
 * Verifies web-next next-intl safety:
 * - locale catalogs do not contain duplicate top-level keys;
 * - generated locale catalogs have the same key set;
 * - web-next-only extra catalogs have the same key set;
 * - literal next-intl calls, e.g. `t("save")`, resolve in every generated
 *   locale.
 *
 * Dynamic keys are intentionally ignored; keep those covered by focused tests
 * or a local allow-list near the owner.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, "..");
const srcRoot = path.join(appRoot, "src");
const messagesRoot = path.join(srcRoot, "lib", "i18n", "messages");
const extraRoot = path.join(srcRoot, "lib", "i18n", "extra");
const locales = ["sv", "en"];

function readJson(file) {
  const source = readFileSync(file, "utf8");
  const seen = new Set();
  const duplicates = [];

  // The generated + extra catalogs are intentionally flat key/value JSON. Keep
  // the duplicate check simple and explicit instead of hiding it in a parser
  // dependency.
  for (const line of source.split("\n")) {
    const match = line.match(/^  "([^"]+)":/);
    if (!match) continue;
    const key = match[1];
    if (seen.has(key)) duplicates.push(key);
    seen.add(key);
  }

  if (duplicates.length > 0) {
    throw new Error(`Duplicate i18n key(s) in ${file}: ${duplicates.join(", ")}`);
  }

  return JSON.parse(source);
}

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const file = path.join(dir, entry);
    const stat = statSync(file);
    if (stat.isDirectory()) {
      if (entry === "messages" && file === messagesRoot) continue;
      walk(file, files);
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry)) files.push(file);
  }
  return files;
}

const catalogs = Object.fromEntries(
  locales.map((locale) => {
    const file = path.join(messagesRoot, `${locale}.json`);
    if (!existsSync(file)) throw new Error(`Missing generated locale catalog: ${file}`);
    return [locale, readJson(file)];
  })
);

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

const extraCatalogs = Object.fromEntries(
  locales.map((locale) => {
    const file = path.join(extraRoot, `${locale}.json`);
    if (!existsSync(file)) throw new Error(`Missing web-next extra locale catalog: ${file}`);
    return [locale, readJson(file)];
  })
);

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

if (parityFailures.length > 0 || missing.length > 0) {
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
        "`node scripts/convert-paraglide-messages.mjs`."
    );
  }
  process.exit(1);
}

console.log("web-next i18n keys OK");
