import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

// Every Playwright spec fails on a Content-Security-Policy violation
// (tests/csp.ts). That only holds while each spec takes `test` from there
// rather than from @playwright/test, so a new spec cannot opt out by accident.

const TESTS = path.resolve(import.meta.dirname, "../../tests");
const specs = readdirSync(TESTS).filter((file) => file.endsWith(".spec.ts"));

it("finds the e2e specs", () => {
  expect(specs.length).toBeGreaterThan(0);
});

it.each(specs)("tests/%s takes test and expect from the CSP fixture", (spec) => {
  const source = readFileSync(path.join(TESTS, spec), "utf8");
  expect(source).toMatch(/^import \{ expect, test \} from "\.\/csp";$/m);
  expect(source).not.toMatch(/import \{[^}]*\b(test|expect)\b[^}]*\} from "@playwright\/test"/);
});
