import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";

// List and overview pages share one readable column (1152 px, PageFrame) and one left edge, so
// the heading stays put from page to page; a form or reading page caps itself narrower on the
// same edge. As in the Svelte app the sidebar holds the place a page is in, so the pages beside
// it share that edge; the assistant catalogue (/dashboard) has no sidebar and is left out.
const PAGES = [
  "/spaces/list",
  "/admin",
  "/admin/users",
  "/admin/models",
  "/admin/roles",
  "/admin/audit-logs",
  "/admin/crawler",
  "/admin/settings",
  "/whats-new"
];

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 }
]) {
  test(`every list and overview page starts on one left edge at ${viewport.width} px`, async ({
    page
  }) => {
    await page.setViewportSize(viewport);
    const space = await createSpace(page, uniqueName("E2E Page Width"));
    const edges: Record<string, number> = {};
    for (const path of PAGES) {
      await page.goto(path);
      // A page with no What's new redirects home; it is the start page's edge then.
      const heading = page.locator("main h1").filter({ visible: true }).first();
      await expect(heading).toBeVisible({ timeout: 15_000 });
      edges[path] = Math.round((await heading.boundingBox())!.x);
    }
    // A space's section pages title themselves in the same column.
    for (const path of [`${space}/overview`, `${space}/members`]) {
      await page.goto(path);
      const heading = page.locator("main h1").first();
      await expect(heading).toBeVisible({ timeout: 15_000 });
      edges[path] = Math.round((await heading.boundingBox())!.x);
    }
    const first = edges[PAGES[0]!]!;
    for (const [path, x] of Object.entries(edges)) {
      expect(
        Math.abs(x - first),
        `${path} starts at ${x}, the start page at ${first}`
      ).toBeLessThanOrEqual(1);
    }
    // The column is 1152 px however wide the screen: on the members page, your own row's role
    // stays within it, beside your address.
    const column = (await page
      .locator("main h1")
      .first()
      .locator("xpath=ancestor::*[contains(concat(' ', @class, ' '), ' max-w-6xl ')][1]")
      .boundingBox())!;
    expect(column.width).toBeLessThanOrEqual(1152);
    const self = page.getByText(/\((du|you)\)$/).first();
    await expect(self).toBeVisible();
    const role = (await self.locator("xpath=following-sibling::*[1]").boundingBox())!;
    expect(role.x + role.width).toBeLessThanOrEqual(column.x + 1152 + 1);
    expect(role.x).toBeGreaterThanOrEqual(column.x);
  });
}
