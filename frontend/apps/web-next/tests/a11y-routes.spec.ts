import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import type { Browser, BrowserContext } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
import { ROUTES, type Fixtures } from "./responsive-routes";
import { AXE_PAGE_RULES, WCAG_22_AA_TAGS } from "../src/test/wcag";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * axe (WCAG 2.2 A/AA: contrast, target size, names, structure) on every screen
 * of tests/responsive-routes.ts, on a phone and an iPad (upright and sideways),
 * in both colour modes.
 * The route list is the one the responsive contract walks, so a screen added
 * to the app is scanned here the day the contract learns about it. A screen
 * the list skips is skipped here too (its reason is in that file).
 *
 * tests/a11y.spec.ts scans the same pages with a menu, dialog or panel open;
 * this spec is about breadth. A rule that cannot hold on one screen goes in
 * EXCEPTIONS with the reason; nothing is excluded globally.
 * A11Y_ROUTES narrows a run to routes matching a regular expression,
 * A11Y_VARIANTS=phone-light,ipad-light to those variants, and
 * A11Y_SHOTS=<dir> saves a screenshot of every screen it opens.
 */

const WCAG_22_AA = WCAG_22_AA_TAGS;
const PAGE_STRUCTURE = AXE_PAGE_RULES;
// Development-only tooling, absent from the production build CI scans.
const DEV_ONLY = ["vite-error-overlay", ".tsqd-parent-container"];

/** route pattern → rule → reason. Fix instead of adding to this. */
const EXCEPTIONS: Record<string, Record<string, string>> = {};

type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];

const VARIANTS = [
  { name: "phone", width: 390, height: 844, scheme: "light" },
  { name: "phone", width: 390, height: 844, scheme: "dark" },
  { name: "ipad", width: 820, height: 1180, scheme: "light" },
  { name: "ipad", width: 820, height: 1180, scheme: "dark" },
  // An iPad mini upright is 744 px: below 768, so the phone layout on a tall screen.
  { name: "ipad-mini", width: 744, height: 1133, scheme: "light" },
  // Held sideways the iPad has the side navigation: a layout of its own.
  { name: "ipad-landscape", width: 1180, height: 820, scheme: "light" },
  { name: "ipad-landscape", width: 1180, height: 820, scheme: "dark" }
] as const;

let fixtures: Fixtures;

test.beforeAll(async ({ browser, baseURL }) => {
  fixtures = await createFixtures(browser, baseURL, "Axe");
});

async function contextFor(
  browser: Browser,
  baseURL: string | undefined,
  variant: (typeof VARIANTS)[number],
  signedIn: boolean
) {
  return browser.newContext({
    baseURL,
    storageState: signedIn ? STORAGE_STATE : { cookies: [], origins: [] },
    viewport: { width: variant.width, height: variant.height },
    colorScheme: variant.scheme,
    reducedMotion: "reduce",
    hasTouch: true,
    isMobile: true
  });
}

for (const variant of VARIANTS) {
  const only = process.env.A11Y_VARIANTS?.split(",");
  if (only && !only.includes(`${variant.name}-${variant.scheme}`)) continue;
  test(
    `every screen passes axe on a ${variant.name}, ${variant.scheme} mode`,
    { tag: ["@vite", "@a11y-routes"] },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const problems: string[] = [];
      const contexts: Record<string, BrowserContext> = {
        in: await contextFor(browser, baseURL, variant, true),
        out: await contextFor(browser, baseURL, variant, false)
      };
      const pages = { in: await contexts.in!.newPage(), out: await contexts.out!.newPage() };
      const shots = process.env.A11Y_SHOTS;
      if (shots) fs.mkdirSync(shots, { recursive: true });

      for (const [pattern, entry] of Object.entries(ROUTES)) {
        if ("skip" in entry) continue;
        if (process.env.A11Y_ROUTES && !new RegExp(process.env.A11Y_ROUTES).test(pattern)) continue;
        const signedIn = entry.auth !== "out";
        const page = pages[signedIn ? "in" : "out"];
        try {
          await openRoute(page, entry.url(fixtures), signedIn);
        } catch (error) {
          problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
          continue;
        }
        if (shots) {
          const file = `${variant.name}-${variant.scheme}-${pattern.replace(/[^a-z0-9]+/gi, "_")}.png`;
          await page.screenshot({ path: path.join(shots, file) });
        }
        const except = EXCEPTIONS[pattern] ?? {};
        const rules = Object.fromEntries([
          ...PAGE_STRUCTURE.map((rule) => [rule, { enabled: true }]),
          ...Object.keys(except).map((rule) => [rule, { enabled: false }])
        ]);
        let builder = new AxeBuilder({ page: page as unknown as AxePage })
          .options({ rules })
          .withTags(WCAG_22_AA);
        for (const selector of DEV_ONLY) builder = builder.exclude(selector);
        const { violations } = await builder.analyze();
        for (const violation of violations) {
          const targets = violation.nodes
            .slice(0, 3)
            .map((node) => node.target.join(" "))
            .join(" | ");
          problems.push(
            `${pattern}: ${violation.id} (${violation.impact}) × ${violation.nodes.length}: ${targets}`
          );
        }
      }
      for (const context of Object.values(contexts)) await context.close();
      if (process.env.A11Y_OUT) {
        fs.appendFileSync(
          process.env.A11Y_OUT,
          JSON.stringify({ variant: `${variant.name}-${variant.scheme}`, problems }) + "\n"
        );
      }
      expect(problems, problems.join("\n")).toEqual([]);
    }
  );
}
