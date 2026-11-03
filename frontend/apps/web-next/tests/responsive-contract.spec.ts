import fs from "node:fs";
import path from "node:path";
import type { Browser, BrowserContext } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute, walkTags } from "./responsive-fixtures";
import { measure, type PageMeasure, type Violation } from "./responsive-measure";
import { ROUTES, type Fixtures } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * The responsive contract: every screen, opened on a handful of real device
 * sizes with touch, must not scroll sideways, and must not hold a target under
 * 44 px, a target outside the screen, two targets on top of each other or text
 * cut off sideways, beyond what tests/responsive-contract.baseline.json lists.
 *
 * The baseline is a ratchet. A violation that is not in it fails the run (fix
 * it, do not add it). A baseline entry that no longer occurs also fails the
 * run, so the file only shrinks. Sideways scroll is never baselined.
 *
 * tests/responsive-routes.ts decides which screens are opened; a unit test
 * keeps it equal to the route tree. CONTRACT_UPDATE=1 rewrites the baseline
 * from the current run; CONTRACT_VIEWPORTS=390x844,820x1180 narrows a run.
 */

const VIEWPORTS = [
  { name: "phone-320", width: 320, height: 568 },
  { name: "phone-390", width: 390, height: 844 },
  // A phone turned: the browser's own bars leave about 300 px of height.
  { name: "phone-landscape", width: 667, height: 300 },
  // A larger phone turned: wider than 768 px but under 500 px tall, it keeps the phone's layout.
  { name: "phone-turned", width: 844, height: 390 },
  { name: "ipad-portrait", width: 820, height: 1180 },
  { name: "ipad-landscape", width: 1180, height: 820 }
].filter(
  ({ width, height }) =>
    !process.env.CONTRACT_VIEWPORTS ||
    process.env.CONTRACT_VIEWPORTS.split(",").includes(`${width}x${height}`)
);

const BASELINE = path.resolve(process.cwd(), "tests/responsive-contract.baseline.json");
type Baseline = Record<string, string[]>;
const baseline: Baseline = fs.existsSync(BASELINE)
  ? JSON.parse(fs.readFileSync(BASELINE, "utf8"))
  : {};
const update = process.env.CONTRACT_UPDATE === "1";
const recorded: Baseline = {};

let fixtures: Fixtures;

test.beforeAll(async ({ browser, baseURL }) => {
  fixtures = await createFixtures(browser, baseURL, "Contract");
});

async function contextFor(
  browser: Browser,
  baseURL: string | undefined,
  vp: (typeof VIEWPORTS)[number],
  signedIn: boolean
) {
  return browser.newContext({
    baseURL,
    storageState: signedIn ? STORAGE_STATE : { cookies: [], origins: [] },
    viewport: { width: vp.width, height: vp.height },
    hasTouch: true,
    isMobile: true
  });
}

for (const vp of VIEWPORTS) {
  test(
    `every screen holds up at ${vp.name} (${vp.width} × ${vp.height})`,
    { tag: walkTags("@contract", vp.name) },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const problems: string[] = [];
      const seen: Record<string, { stable: Set<string>; either: Set<string> }> = {};
      const contexts: Record<string, BrowserContext> = {
        in: await contextFor(browser, baseURL, vp, true),
        out: await contextFor(browser, baseURL, vp, false)
      };
      const pages = { in: await contexts.in!.newPage(), out: await contexts.out!.newPage() };

      for (const [pattern, entry] of Object.entries(ROUTES)) {
        if ("skip" in entry) continue;
        if (process.env.CONTRACT_ROUTES && !new RegExp(process.env.CONTRACT_ROUTES).test(pattern))
          continue;
        const signedIn = entry.auth !== "out";
        const page = pages[signedIn ? "in" : "out"];
        try {
          await openRoute(page, entry.url(fixtures), signedIn);
        } catch (error) {
          problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
          continue;
        }
        const result = await measure(page);
        if (result.overflowDoc > 0 || result.overflowPanel > 1) {
          problems.push(
            `${pattern}: scrolls sideways (page ${result.overflowDoc} px, panel ${result.overflowPanel} px)`
          );
        }
        const key = `${vp.name}|${pattern}`;
        const names = (r: PageMeasure) =>
          new Set(r.violations.map((v: Violation) => `${v.kind} ${v.key}`));
        const allowed = new Set(baseline[key] ?? []);
        let stable = names(result);
        let either = stable;
        if (!update && (stable.size !== allowed.size || [...stable].some((e) => !allowed.has(e)))) {
          // A banner or menu that arrives late makes one measurement differ from the
          // next: a violation is new only if it shows twice, gone only if it shows in neither.
          await page.waitForTimeout(1500);
          const again = names(await measure(page));
          stable = new Set([...stable].filter((e) => again.has(e)));
          either = new Set([...either, ...again]);
        }
        seen[key] = { stable, either };
      }
      for (const context of Object.values(contexts)) await context.close();

      for (const [key, { stable, either }] of Object.entries(seen)) {
        recorded[key] = [...stable].sort();
        if (update) continue;
        const allowed = new Set(baseline[key] ?? []);
        for (const entry of stable) if (!allowed.has(entry)) problems.push(`${key}: NEW ${entry}`);
        for (const entry of allowed)
          if (!either.has(entry))
            problems.push(`${key}: baseline entry no longer occurs (remove it) ${entry}`);
      }
      if (update) {
        const merged = { ...baseline, ...recorded };
        fs.writeFileSync(
          BASELINE,
          JSON.stringify(Object.fromEntries(Object.entries(merged).sort()), null, 1) + "\n"
        );
      }
      expect(problems, problems.join("\n")).toEqual([]);
    }
  );
}
