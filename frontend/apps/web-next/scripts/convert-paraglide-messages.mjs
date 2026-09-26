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
 * Every string web-next owns lives in src/lib/i18n/extra/{locale}.json (its
 * own keys and its wording for apps/web keys), merged last so it wins. The
 * output, src/lib/i18n/messages/{locale}.json, is generated: never edit it.
 *
 * Usage: bun run i18n:convert
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
