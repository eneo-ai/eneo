#!/usr/bin/env node
/**
 * Generates web-next's next-intl catalogs, src/lib/i18n/messages/{sv,en}.json,
 * from the SvelteKit app's Paraglide catalogs (apps/web/messages) with
 * src/lib/i18n/extra/{sv,en}.json merged over them (extra wins).
 *
 * messages/* is generated: never edit it. Every string web-next owns lives in
 * extra/ (sv and en with the same keys): new keys, and web-next's wording for
 * an apps/web key. Everything else comes from apps/web, so a run also picks up
 * apps/web's new keys and wording and drops the keys it deleted. `bun run
 * lint` (scripts/check-i18n.mjs) fails while messages/* differs from what a
 * run writes.
 *
 * Messages that need manual review are flagged on stdout and copied through
 * unchanged:
 *   - non-string values (Paraglide variants/plurals)
 *   - keys containing "." (next-intl treats dots as namespace separators)
 *   - apostrophes directly before "{" or "}" (ICU escape semantics differ)
 *   - "<" before a letter (markup or a <placeholder>; ICU parses tags)
 * To fix one for web-next, put its ICU version in extra/; that clears the flag.
 *
 * Usage: bun run i18n:convert
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  appRoot,
  buildLocale,
  diffCatalogs,
  locales,
  messagesDir,
  serializeCatalog
} from "./i18n-catalogs.mjs";

mkdirSync(messagesDir, { recursive: true });

// The previous catalog only feeds the summary; after a bad merge it may not
// parse, and regenerating it is the fix.
function readPrevious(file) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

for (const locale of locales) {
  const { paths, messages, flagged } = buildLocale(locale);
  const previous = readPrevious(paths.messages);

  writeFileSync(paths.messages, serializeCatalog(messages));

  const count = `${locale}: ${Object.keys(messages).length} messages written`;
  if (!previous) {
    console.log(count);
  } else {
    const { dropped, changed, added } = diffCatalogs(previous, messages);
    console.log(
      `${count} (${added.length} added, ${changed.length} changed, ${dropped.length} removed)`
    );
    // A removal is the one change that can break web-next: apps/web deletes
    // keys it stops using, even when web-next still uses them.
    if (dropped.length > 0) {
      const extra = path.relative(appRoot, paths.extra);
      console.log(`${locale}: removed because neither apps/web nor ${extra} has them any more:`);
      for (const key of dropped) console.log(`  - ${key}`);
      console.log(
        "  If web-next still uses one, add it back to extra/ (sv and en; git has the old text) " +
          "and run `bun run i18n:convert` again."
      );
    }
  }

  if (flagged.length > 0) {
    console.log(`${locale}: ${flagged.length} message(s) need manual review:`);
    for (const entry of flagged) console.log(`  - ${entry}`);
  }
}
