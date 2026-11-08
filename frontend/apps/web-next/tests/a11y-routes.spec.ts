import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { contrastIncomplete } from "./contrast-incomplete";
import { contrastProbe } from "./contrast-probe";
import { expectNoCollapsedTableColumns, expectNothingBusy, expectShellHoldsStill } from "./helpers";
import { leftEdgeProbe } from "./left-edge-probe";
import { createFixtures, walkRoutes, walkTags } from "./responsive-fixtures";
import type { Fixtures } from "./responsive-routes";
import { selectedProbe } from "./selected-probe";
import { DEV_ONLY, probeBaseline, type Cell } from "./ui-probes";
import { AXE_PAGE_RULES, WCAG_22_AA_TAGS } from "../src/test/wcag";

/*
 * axe (WCAG 2.2 A/AA: contrast, target size, names, structure) on every screen
 * of tests/responsive-routes.ts, on a phone and an iPad (upright and sideways),
 * in both colour modes.
 * The route list is the one the responsive contract walks, so a screen added
 * to the app is scanned here the day the contract learns about it. A screen
 * the list skips is skipped here too (its reason is in that file).
 *
 * tests/a11y.spec.ts scans the same pages with a menu, dialog or panel open;
 * this spec is about breadth. CHECKS holds what must be on a screen before it is
 * scanned, so a scan cannot pass on a screen that never arrived. A rule that cannot hold on one screen goes in
 * EXCEPTIONS with the reason; nothing is excluded globally.
 * A11Y_ROUTES narrows a run to routes matching a regular expression,
 * A11Y_VARIANTS=phone-light,ipad-light to those variants, and
 * A11Y_SHOTS=<dir> saves a screenshot of every screen it opens.
 * Contrast axe could not judge is held to tests/contrast-incomplete.baseline.json
 * (tests/contrast-incomplete.ts; CONTRAST_UPDATE=1 rewrites it).
 * The UI probes (tests/ui-probes.ts: contrast with hover, pressed and focus forced, selected
 * states, the shared left edge) run on the same visit, each held to its own baseline
 * (PROBES_UPDATE=1 rewrites them); what they could not judge is attached for review.
 */

const WCAG_22_AA = WCAG_22_AA_TAGS;
const PAGE_STRUCTURE = AXE_PAGE_RULES;
// Contrast last: it forces states on the page, and the others read it at rest.
const PROBES = { selected: selectedProbe, "left-edge": leftEdgeProbe, contrast: contrastProbe };

/** route pattern → rule → reason. Fix instead of adding to this. */
const EXCEPTIONS: Record<string, Record<string, string>> = {};

/** The screen `page` shows, at a layout's width. */
type Screen = { page: Page; fixtures: Fixtures; width: number };

const heading = ({ page }: Screen, level: number, name: RegExp | string) =>
  expect(page.getByRole("heading", { level, name })).toBeVisible();
/** Below 1024 px a Konto page has its own heading; sideways, "Konto" over its tabs. */
const kontoPage = ({ page, width }: Screen, title: RegExp) =>
  expect(
    page.getByRole("heading", { level: 1, name: width < 1024 ? title : /^(Konto|Account)$/ })
  ).toBeAttached();

/**
 * Route pattern → what must be on the screen before it is scanned, with nothing left
 * loading. These routes also hold the checks axe has no rule for: a column that collapsed, a
 * document that scrolls under the shell.
 */
const CHECKS: Record<string, (screen: Screen) => Promise<void>> = {
  "/account": (screen) => heading(screen, 1, /^(Konto|Account)$/),
  "/account/api-keys": (screen) => kontoPage(screen, /^(Mina API-nycklar|My API keys)$/),
  "/account/appearance": ({ page }) =>
    expect(page.getByRole("radiogroup", { name: /^(Tema|Theme)$/ })).toBeVisible(),
  "/account/copy-format": (screen) => kontoPage(screen, /^(Kopieringsformat|Copy format)$/),
  "/account/integrations": (screen) => kontoPage(screen, /^(Integrationer|Integrations)$/),
  "/account/password": (screen) => kontoPage(screen, /^(Byt lösenord|Change password)$/),
  "/admin": (screen) => heading(screen, 1, /^(Översikt|Overview)$/),
  "/admin/models": (screen) => heading(screen, 2, "E2E Mock Provider"),
  "/admin/users": async (screen) => {
    await heading(screen, 1, /^(Användare|Users)$/);
    await expect(screen.page.getByRole("main").getByText(/^\d+ (användare|users?)$/)).toBeVisible();
  },
  "/spaces/$/apps": (screen) => heading(screen, 2, /^(Appar|Apps)$/),
  "/spaces/$/apps/$": async ({ page, fixtures }) => {
    await expect(page.getByRole("tab", { name: /^(Resultat|Results)$/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /^(Redigera|Edit)$/ })).toHaveAttribute(
      "href",
      `${fixtures.space}/apps/${fixtures.app}/edit`
    );
  },
  "/spaces/$/apps/$/edit": (screen) => heading(screen, 1, /^Protokoll /),
  "/spaces/$/assistants": (screen) => heading(screen, 2, /^(Assistenter|Assistants)$/),
  "/spaces/$/assistants/$/edit": (screen) => heading(screen, 1, /^Bygglov /),
  "/spaces/$/members": (screen) => heading(screen, 2, /^(Medlemmar|Members)$/),
  "/spaces/$/overview": async (screen) => {
    // A phone's and a tablet's space header names the space (#1328).
    await heading(screen, 1, screen.fixtures.spaceName);
    // A phone lists what manages the space; tablets keep a tab for each.
    await expect(
      screen.page.getByRole("region", { name: /^(Hantera ytan|Manage space)$/ })
    ).toHaveCount(screen.width < 768 ? 1 : 0);
  },
  "/spaces/list": ({ page }) => expect(page.getByRole("heading", { level: 1 })).toBeVisible(),
  "/whats-new": (screen) => heading(screen, 1, /^(Nyheter|What's new)$/)
};

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

for (const variant of VARIANTS) {
  const only = process.env.A11Y_VARIANTS?.split(",");
  if (only && !only.includes(`${variant.name}-${variant.scheme}`)) continue;
  test(
    `every screen passes axe on a ${variant.name}, ${variant.scheme} mode`,
    { tag: walkTags("@a11y-routes", variant.name) },
    async ({ browser, baseURL }) => {
      test.setTimeout(15 * 60_000);
      const problems: string[] = [];
      const reviews: string[] = [];
      const cell: Cell = {
        viewport: { width: variant.width, height: variant.height },
        theme: variant.scheme,
        touch: true
      };
      const shots = process.env.A11Y_SHOTS;
      if (shots) fs.mkdirSync(shots, { recursive: true });

      const walk = {
        baseURL,
        fixtures,
        context: {
          viewport: cell.viewport,
          colorScheme: variant.scheme,
          reducedMotion: "reduce",
          hasTouch: true,
          isMobile: true
        },
        only: process.env.A11Y_ROUTES
      } as const;
      const found = await walkRoutes(browser, walk, async (page, pattern) => {
        const problems: string[] = [];
        const check = CHECKS[pattern];
        if (check) {
          try {
            await check({ page, fixtures, width: variant.width });
            await expectNothingBusy(page);
          } catch (error) {
            problems.push(`${pattern}: not ready (${String(error).split("\n")[0]})`);
          }
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
          .options({ rules, ancestry: true })
          .withTags(WCAG_22_AA);
        for (const selector of DEV_ONLY) builder = builder.exclude(selector);
        const { violations, incomplete } = await builder.analyze();
        const scan = `${variant.name}-${variant.scheme}|${pattern}`;
        // Text axe could not judge (over a gradient, image or another element) may not grow.
        problems.push(...contrastIncomplete(scan, incomplete));
        for (const violation of violations) {
          const targets = violation.nodes
            .slice(0, 3)
            .map((node) => node.target.join(" "))
            .join(" | ");
          problems.push(
            `${pattern}: ${violation.id} (${violation.impact}) × ${violation.nodes.length}: ${targets}`
          );
        }
        for (const [name, probe] of Object.entries(PROBES)) {
          try {
            const found = await probe(page, cell);
            problems.push(...probeBaseline(name, scan, found));
            for (const { key, detail } of found.filter((problem) => problem.review))
              reviews.push(`${scan}: ${name} ${key}: ${detail}`);
          } catch (error) {
            problems.push(`${scan}: the ${name} probe failed (${String(error).split("\n")[0]})`);
          }
        }
        if (check) {
          try {
            await expectNoCollapsedTableColumns(page);
            await expectShellHoldsStill(page);
          } catch (error) {
            problems.push(`${pattern}: ${String(error).split("\n")[0]}`);
          }
        }
        return problems;
      });
      problems.push(...found);
      if (reviews.length)
        await test.info().attach("ui-probes-review.txt", { body: reviews.join("\n") });
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
