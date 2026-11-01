import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { viteRoutePaths } from "../../scripts/check-route-parity.mjs";
import { ROUTES, SKIP_BUDGET, skipped } from "../../tests/responsive-routes";

const appDir = path.resolve(import.meta.dirname, "../..");
const routes: string[] = viteRoutePaths(
  readFileSync(path.join(appDir, "src/routeTree.gen.ts"), "utf8")
);

// The responsive contract (tests/responsive-contract.spec.ts) walks this list:
// a screen it does not know about is a screen nobody checked on a phone.
describe("the responsive contract's routes", () => {
  it("names every route of the app, and no route that is gone", () => {
    const listed = Object.keys(ROUTES);
    expect(routes.filter((route) => !listed.includes(route))).toEqual([]);
    expect(listed.filter((route) => !routes.includes(route))).toEqual([]);
  });

  it("explains every route it does not open, and opens no more than it has to leave", () => {
    for (const [route, entry] of skipped()) {
      expect("skip" in entry && entry.skip.length > 20, route).toBe(true);
    }
    expect(skipped().length).toBeLessThanOrEqual(SKIP_BUDGET);
  });

  it("opens the page every redirect lands on", () => {
    for (const [route, entry] of Object.entries(ROUTES)) {
      if (!("redirectsTo" in entry) || !entry.redirectsTo) continue;
      expect("url" in (ROUTES[entry.redirectsTo] ?? {}), `${route} → ${entry.redirectsTo}`).toBe(
        true
      );
    }
  });
});
