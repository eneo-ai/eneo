import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { audioFlow } from "./flows-fixture";
import { apiRequest, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

/** A space with a published audio flow and, created after it, a draft that says what it is for. */
async function listedFlows(page: Page) {
  const published = await audioFlow(page);
  const list = published.url.replace(/\/[^/]+$/, "");
  const draft = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
    method: "POST",
    body: {
      space_id: list.split("/")[2],
      name: uniqueName("E2E utkast"),
      description: "Sammanställer remissvar per avsnitt."
    }
  });
  return { list, draft: draft.name };
}

const search = (page: Page) => page.getByRole("textbox", { name: "Sök flöden" });

test(
  "a computer finds a flow by its description or its state, and a reload keeps the search and the filter",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(120_000);
    const { list, draft } = await listedFlows(page);
    await page.goto(list);
    const table = page.getByRole("table", { name: "Flöden" });
    // The last changed first, with what it takes in under the name.
    await expect(table.getByRole("link").first()).toHaveText(draft);
    await expect(table.getByText("Indata: Ljud")).toBeVisible();
    await expect(page.getByText("2 flöden · sorterade efter senast ändrad")).toBeVisible();

    await search(page).fill("remissvar");
    await expect(table.getByRole("link")).toHaveCount(1);
    await expect(page).toHaveURL(/\?q=remissvar$/);
    await page.reload();
    await expect(search(page)).toHaveValue("remissvar");
    await expect(table.getByRole("link", { name: draft })).toBeVisible();

    await search(page).fill("finns inte");
    await expect(
      page.getByRole("heading", { name: "Inga flöden matchar din sökning" })
    ).toBeVisible();
    await page.getByRole("button", { name: "Rensa sökningen" }).click();
    await expect(search(page)).toBeFocused();
    await expect(table.getByRole("link")).toHaveCount(2);

    await page.getByRole("radio", { name: "Publicerade" }).click();
    await expect(table.getByRole("link")).toHaveCount(1);
    await expect(table.getByRole("link", { name: draft })).toHaveCount(0);
    await expect(page).toHaveURL(/\?status=published$/);
    await page.reload();
    await expect(page.getByRole("radio", { name: "Publicerade" })).toBeChecked();
    await expect(table.getByRole("link")).toHaveCount(1);
  }
);

test.describe("on a phone", () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true });

  test(
    "searches and filters the rows with a thumb, without scrolling sideways",
    { tag: "@vite" },
    async ({ page }) => {
      test.setTimeout(120_000);
      const { list, draft } = await listedFlows(page);
      await page.goto(`${list}?status=drafts`);
      const rows = page.getByRole("list", { name: "Flöden" });
      await expect(page.getByRole("radio", { name: "Utkast" })).toBeChecked();
      await expect(rows.getByRole("link")).toHaveCount(1);
      await expect(rows.getByRole("link", { name: new RegExp(draft) })).toBeVisible();

      // Every state is a 44 px target, and the page fits 320 px.
      for (const name of ["Alla", "Publicerade", "Utkast"]) {
        const box = await page.getByRole("radio", { name }).boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true);

      await page.getByRole("radio", { name: "Publicerade" }).tap();
      await expect(rows.getByRole("link")).toHaveCount(1);
      await expect(rows.getByRole("link", { name: new RegExp(draft) })).toHaveCount(0);

      await search(page).fill("remissvar");
      await expect(
        page.getByRole("heading", { name: "Inga flöden matchar din sökning" })
      ).toBeVisible();
      await page.getByRole("button", { name: "Rensa sökningen" }).tap();
      await page.getByRole("radio", { name: "Alla" }).tap();
      await expect(rows.getByRole("link")).toHaveCount(2);
      await expect(page).toHaveURL(new RegExp(`${list}$`));
    }
  );
});
