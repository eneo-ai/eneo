/**
 * How web-next's message catalogs are built, shared by
 * convert-paraglide-messages.mjs (writes them) and check-i18n.mjs (checks that
 * the committed ones are what a run writes).
 *
 * src/lib/i18n/messages/{locale}.json is the SvelteKit app's Paraglide catalog
 * (apps/web/messages/{locale}.json) with src/lib/i18n/extra/{locale}.json
 * merged over it: extra holds every string web-next owns, both its own keys
 * and its wording for apps/web keys.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const locales = ["sv", "en"];

const sourceDir = path.resolve(appRoot, "..", "web", "messages");
const extraDir = path.join(appRoot, "src", "lib", "i18n", "extra");
export const messagesDir = path.join(appRoot, "src", "lib", "i18n", "messages");

export function catalogPaths(locale) {
  return {
    source: path.join(sourceDir, `${locale}.json`),
    extra: path.join(extraDir, `${locale}.json`),
    messages: path.join(messagesDir, `${locale}.json`)
  };
}

/** Parses a flat web-next catalog, rejecting duplicate keys (JSON.parse keeps the last). */
export function readCatalog(file) {
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

/**
 * The catalog a converter run writes for one locale. Paraglide stores flat
 * key → string maps with `{param}` interpolation, which is already valid ICU
 * for the simple cases; messages that need manual review are copied through
 * unchanged and returned in `flagged`, unless extra replaces them.
 */
function buildMessages(source, extra) {
  const messages = {};
  const flagged = [];

  for (const [key, value] of Object.entries(source)) {
    if (key === "$schema") continue;
    messages[key] = value;
    if (Object.hasOwn(extra, key)) continue;

    if (typeof value !== "string") {
      flagged.push(`${key}: non-string value (Paraglide variant/plural), copied as-is`);
      continue;
    }
    if (key.includes(".")) {
      flagged.push(`${key}: key contains "." (next-intl namespace separator)`);
    }
    if (/'[{}]/.test(value)) {
      flagged.push(`${key}: apostrophe before "{" or "}" (ICU escape, needs '' doubling)`);
    }
    if (/<\/?[A-Za-z]/.test(value)) {
      flagged.push(`${key}: "<" before a letter (markup or <placeholder>; ICU parses tags)`);
    }
  }

  // Extra wins: web-next's wording replaces apps/web's for the same key.
  return { messages: Object.assign(messages, extra), flagged };
}

/** Reads one locale's inputs and builds its catalog. */
export function buildLocale(locale) {
  const paths = catalogPaths(locale);
  const source = JSON.parse(readFileSync(paths.source, "utf8"));
  const extra = readCatalog(paths.extra);
  return { paths, extra, ...buildMessages(source, extra) };
}

/** What writing `expected` over `current` would change. */
export function diffCatalogs(current, expected) {
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  return {
    dropped: Object.keys(current).filter((key) => !Object.hasOwn(expected, key)),
    changed: Object.keys(current).filter(
      (key) => Object.hasOwn(expected, key) && !same(current[key], expected[key])
    ),
    added: Object.keys(expected).filter((key) => !Object.hasOwn(current, key))
  };
}

export function serializeCatalog(catalog) {
  return JSON.stringify(catalog, null, 2) + "\n";
}
