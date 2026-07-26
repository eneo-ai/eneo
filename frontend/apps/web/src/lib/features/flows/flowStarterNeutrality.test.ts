import { describe, expect, it } from "vitest";
import en from "../../../../messages/en.json";
import sv from "../../../../messages/sv.json";

/**
 * F-22: the starter copy ships to every deployment, so it must not carry one
 * municipality's vocabulary. Guarding the catalogue rather than one module
 * keeps the invariant true however the starter is later refactored.
 */
const DOMAIN_TERMS = {
  en: ["case file", "decision brief", "municipal", "municipality", "authority register"],
  sv: ["ärende", "beslut", "verksamhet", "myndighet", "diarie", "kommun"]
} as const;

const starterKeys = (catalogue: Record<string, string>) =>
  Object.entries(catalogue).filter(([key]) => key.startsWith("flow_starter_"));

describe("flow starter copy", () => {
  it.each([
    ["en", en as Record<string, string>, DOMAIN_TERMS.en],
    ["sv", sv as Record<string, string>, DOMAIN_TERMS.sv]
  ])("carries no domain-specific vocabulary in %s", (_locale, catalogue, domainTerms) => {
    const messages = starterKeys(catalogue);
    expect(messages.length).toBeGreaterThan(0);
    for (const [key, value] of messages) {
      for (const term of domainTerms) {
        expect(value.toLowerCase(), `${key} must stay domain-neutral`).not.toContain(term);
      }
    }
  });
});
