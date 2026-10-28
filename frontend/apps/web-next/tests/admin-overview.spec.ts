import { expect, test } from "./csp";

test.describe("the admin overview on a phone (decision 30)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("lists the areas as rows with how each stands, after anything that needs an admin", async ({
    page
  }) => {
    await page.goto("/admin");
    const areas = page.getByRole("region", { name: "Läget just nu" });
    await expect(areas).toBeVisible();
    // The cards are the tablet's.
    await expect(page.getByRole("region", { name: "Aktiva användare" })).toBeHidden();

    const rows = areas.getByRole("link");
    // The name and its state, read as one (Chromium adds a space before the
    // visually hidden comma: the same pause).
    await expect(rows.first()).toHaveAccessibleName(/^Användare ?, \d/);
    // The whole row is the link's target (globals.css 12b).
    for (const row of await areas.getByRole("listitem").all()) {
      expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    // Anything that needs an admin comes first, each row to its page.
    const attention = page.getByRole("region", { name: "Behöver åtgärd" });
    if (await attention.isVisible()) {
      const [first, second] = await Promise.all([attention.boundingBox(), areas.boundingBox()]);
      expect(first!.y).toBeLessThan(second!.y);
      for (const row of await attention.getByRole("link").all()) {
        await expect(row).toHaveAttribute("href", /^\/admin\//);
        await expect(row).toHaveAccessibleName(/^(Fel|Varning): /);
      }
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
  });
});

test.describe("the admin overview on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keeps one card per area", async ({ page }) => {
    await page.goto("/admin");
    await expect(page.getByRole("region", { name: "Aktiva användare" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Läget just nu" })).toBeHidden();
  });
});
