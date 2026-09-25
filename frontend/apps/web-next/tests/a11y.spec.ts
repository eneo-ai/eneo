import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import { createSpace, uniqueName } from "./helpers";

// Page-level WCAG 2.2 A/AA scans (ACCESSIBILITY.md → Automated checks). axe-core
// runs in real Chromium, so colour contrast (1.4.3, 1.4.11) and target size
// (2.5.8) are measured on the rendered page, in both colour modes. Any
// violation fails the test.
//
// Excluding a region or rule needs a comment with the reason and an issue
// link next to it (ACCESSIBILITY.md → Exceptions). Fix instead when you can.

// Development-only tooling, absent from production builds (what CI scans):
// the Next.js dev overlay and the TanStack Query devtools button.
const DEV_ONLY = ["nextjs-portal", ".tsqd-parent-container"];

// @axe-core/playwright is typed against the workspace's hoisted playwright-core
// (apps/web's newer Playwright); it only uses Page APIs both versions share.
type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];

async function expectNoAxeViolations(page: Page) {
  let builder = new AxeBuilder({ page: page as unknown as AxePage }).withTags(WCAG_22_AA_TAGS);
  for (const selector of DEV_ONLY) builder = builder.exclude(selector);
  const { violations } = await builder.analyze();
  const report = violations.map((violation) => ({
    rule: violation.id,
    impact: violation.impact,
    help: violation.help,
    helpUrl: violation.helpUrl,
    targets: violation.nodes.map((node) => node.target.join(" "))
  }));
  expect(report, `WCAG 2.2 A/AA violations on ${page.url()}`).toEqual([]);
}

/** Opens a route, waits until it shows real content, then scans it. */
async function scan(page: Page, path: string, ready: () => Promise<void>) {
  await page.goto(path);
  await ready();
  // LoadingState skeletons are aria-busy: scan the loaded page, not a skeleton.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await expectNoAxeViolations(page);
}

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`WCAG 2.2 AA, ${colorScheme} mode`, () => {
    // Reduced motion: no fade-ins mid-scan, so contrast is measured at rest.
    test.use({ colorScheme, contextOptions: { reducedMotion: "reduce" } });

    test.describe("signed out", () => {
      test.use({ storageState: { cookies: [], origins: [] } });

      test("login", async ({ page }) => {
        await scan(page, "/login", async () => {
          await expect(page.locator('input[name="email"]')).toBeVisible();
        });
      });
    });

    test("personal chat", async ({ page }) => {
      await scan(page, "/spaces/personal/chat", async () => {
        await expect(page.locator("textarea").last()).toBeVisible();
      });
    });

    test("spaces list", async ({ page }) => {
      await scan(page, "/spaces/list", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      });
    });

    test("assistant catalogue (dashboard)", async ({ page }) => {
      await scan(page, "/dashboard", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      });
    });

    // Phone layouts: the top bar or the chat's own header instead of the
    // SideNav, and a touch pointer, so the 44 px touch targets apply.
    test.describe("phone (390 × 844)", () => {
      test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

      test("personal chat", async ({ page }) => {
        await scan(page, "/spaces/personal/chat", async () => {
          await expect(page.locator("textarea").last()).toBeVisible();
        });
      });

      test("spaces list", async ({ page }) => {
        await scan(page, "/spaces/list", async () => {
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        });
      });
    });

    test("space overview and knowledge", async ({ page }) => {
      const name = uniqueName(`E2E A11y Space ${colorScheme}`);
      const space = await createSpace(page, name);

      await scan(page, `${space}/overview`, async () => {
        await expect(page.getByRole("heading", { name })).toBeVisible();
      });
      await scan(page, `${space}/knowledge`, async () => {
        await expect(page.getByRole("heading", { name: /kunskap|knowledge/i })).toBeVisible();
      });
    });

    test("admin models", async ({ page }) => {
      await scan(page, "/admin/models", async () => {
        await expect(page.getByRole("tab", { name: /migreringshistorik/i })).toBeVisible();
      });
    });

    test("account", async ({ page }) => {
      await scan(page, "/account", async () => {
        await expect(page.getByText(/byt lösenord/i).first()).toBeVisible();
      });
    });
  });
}

test("the skip link is the first tab stop and moves focus to the main content", async ({
  page
}) => {
  await page.goto("/spaces/list");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: /hoppa till innehåll|skip to content/i });
  await expect(skipLink).toBeFocused();
  // Visually hidden until focused (sr-only, a 1px clip): with focus it must be
  // shown at full size (2.4.7) and be a real target (2.5.8).
  const box = await skipLink.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThanOrEqual(24);
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);

  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});
