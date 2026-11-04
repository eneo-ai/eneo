import fs from "node:fs";
import path from "node:path";
import { expect, test } from "./csp";
import { hiddenFocusProbe } from "./hidden-focus-probe";
import { createFixtures, walkRoutes, walkTags } from "./responsive-fixtures";
import { measure, type PageMeasure, type Violation } from "./responsive-measure";
import type { Fixtures } from "./responsive-routes";

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
 * The sizes marked `keyboard` also Tab through each screen (tests/hidden-focus-probe.ts): it
 * is the same visit, last, since Tabbing changes what the page shows.
 *
 * tests/responsive-routes.ts decides which screens are opened; a unit test
 * keeps it equal to the route tree. CONTRACT_UPDATE=1 rewrites the baseline
 * from the current run; CONTRACT_VIEWPORTS=390x844,820x1180 narrows a run.
 */

const VIEWPORTS = [
  { name: "phone-320", width: 320, height: 568 },
  { name: "phone-390", width: 390, height: 844, keyboard: true },
  // A phone turned: the browser's own bars leave about 300 px of height.
  { name: "phone-landscape", width: 667, height: 300, keyboard: true },
  // A larger phone turned: wider than 768 px but under 500 px tall, it keeps the phone's layout.
  { name: "phone-turned", width: 844, height: 390 },
  { name: "ipad-portrait", width: 820, height: 1180, keyboard: true },
  { name: "ipad-landscape", width: 1180, height: 820, keyboard: true }
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

for (const vp of VIEWPORTS) {
  test(
    `every screen holds up at ${vp.name} (${vp.width} × ${vp.height})`,
    { tag: walkTags("@contract", vp.name) },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const problems: string[] = [];
      const seen: Record<string, { stable: Set<string>; either: Set<string> }> = {};
      const walk = {
        baseURL,
        fixtures,
        context: {
          viewport: { width: vp.width, height: vp.height },
          hasTouch: true,
          isMobile: true
        },
        only: process.env.CONTRACT_ROUTES
      };
      const found = await walkRoutes(browser, walk, async (page, pattern) => {
        const problems: string[] = [];
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
        if (vp.keyboard) problems.push(...(await hiddenFocusProbe(page, pattern)));
        return problems;
      });
      problems.push(...found);

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
