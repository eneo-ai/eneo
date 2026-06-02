import { describe, expect, it } from "vitest";
import en from "../../../../../messages/en.json";
import sv from "../../../../../messages/sv.json";

/**
 * Guards the audit i18n contract that complements the compile-time check in
 * audit-action-labels.ts / audit-category-labels.ts.
 *
 * The `satisfies Record<ActionType | CategoryType, …>` in those modules already
 * forces every backend key to have messages (a new enum member fails
 * `bun run check`). These runtime checks add what the type system can't see:
 * en/sv parity, name↔description pairing, and non-empty values.
 */

const EN = en as Record<string, string>;
const SV = sv as Record<string, string>;

const keys = (o: Record<string, string>) => Object.keys(o).filter((k) => k !== "$schema");

const auditNames = (o: Record<string, string>, prefix: string) =>
  keys(o).filter((k) => k.startsWith(prefix) && !k.endsWith("_description"));

describe("message locale parity", () => {
  it("en.json and sv.json have identical key sets", () => {
    const onlyEn = keys(EN).filter((k) => !(k in SV));
    const onlySv = keys(SV).filter((k) => !(k in EN));
    expect({ onlyEn, onlySv }).toEqual({ onlyEn: [], onlySv: [] });
  });
});

describe.each([
  ["audit_action_", "actions"],
  ["audit_category_", "categories"]
])("audit %s messages", (prefix, _label) => {
  for (const [localeName, locale] of [
    ["en", EN],
    ["sv", SV]
  ] as const) {
    it(`${localeName}: every name has a non-empty description counterpart`, () => {
      for (const nameKey of auditNames(locale, prefix)) {
        const descKey = `${nameKey}_description`;
        expect(locale[nameKey]?.length, `${nameKey} is empty`).toBeGreaterThan(0);
        expect(locale[descKey]?.length, `${descKey} missing or empty`).toBeGreaterThan(0);
      }
    });
  }
});
