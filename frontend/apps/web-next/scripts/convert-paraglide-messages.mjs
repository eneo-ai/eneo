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
 * Keys that exist only in web-next live in src/lib/i18n/extra/{locale}.json
 * and are merged last (they win over converted keys).
 *
 * Usage: bun run i18n:convert
 *
 * DRIFT: do not run this until the catalogs are reconciled. About 750
 * web-next keys were added to messages/*.json directly instead of to
 * extra/*.json, so a run drops them (and changes some values and adds keys
 * from apps/web). Until they move into extra/, add new keys to all four
 * catalogs (extra/ and messages/, sv and en) by hand; `bun run lint` checks
 * that the locales match.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { buildLocale, locales, messagesDir, serializeCatalog } from "./i18n-catalogs.mjs";

mkdirSync(messagesDir, { recursive: true });

for (const locale of locales) {
  const { paths, messages, flagged } = buildLocale(locale);

  writeFileSync(paths.messages, serializeCatalog(messages));
  console.log(`${locale}: ${Object.keys(messages).length} messages written`);
  if (flagged.length > 0) {
    console.log(`${locale}: ${flagged.length} message(s) need manual review:`);
    for (const entry of flagged) console.log(`  - ${entry}`);
  }
}
