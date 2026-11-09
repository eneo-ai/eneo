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
const groups = (page: Page) => ({
  published: page.getByRole("region", { name: "Publicerad", exact: true }),
  drafts: page.getByRole("region", { name: "Utkast", exact: true })
});

test(
  "a computer sees published flows apart from drafts, finds one by its description, and a reload keeps the search",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(120_000);
    const { list, draft } = await listedFlows(page);
    await page.goto(list);
    const { published, drafts } = groups(page);
    // Each flow under its state, the last changed first, with what it takes in on its card.
    await expect(published.getByRole("link")).toHaveCount(1);
    await expect(published.getByText("Indata: Ljud")).toBeVisible();
    await expect(drafts.getByRole("link", { name: draft, exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sortera: Senast ändrad · Fallande", exact: true })
    ).toBeVisible();

    await search(page).fill("remissvar");
    await expect(drafts.getByRole("link")).toHaveCount(1);
    await expect(published).toHaveCount(0);
    await expect(page).toHaveURL(/\?q=remissvar$/);
    await page.reload();
    await expect(search(page)).toHaveValue("remissvar");
    await expect(drafts.getByRole("link", { name: draft, exact: true })).toBeVisible();
    await expect(published).toHaveCount(0);

    await search(page).fill("finns inte");
    await expect(
      page.getByRole("heading", { name: "Inga flöden matchar din sökning" })
    ).toBeVisible();
    await page.getByRole("button", { name: "Rensa sökningen" }).click();
    await expect(search(page)).toBeFocused();
    await expect(published.getByRole("link")).toHaveCount(1);
    await expect(drafts.getByRole("link")).toHaveCount(1);
    await expect(page).toHaveURL(new RegExp(`${list}$`));

    // The table says the same: what a flow takes in under its name, its state in a column.
    await page.getByRole("button", { name: "Lista", exact: true }).click();
    const publishedTable = published.getByRole("table", { name: "Flöden · Publicerad" });
    await expect(publishedTable.getByText("Indata: Ljud")).toBeVisible();
    await expect(publishedTable.getByRole("columnheader", { name: /Status/ })).toBeVisible();
    await expect(
      drafts
        .getByRole("table", { name: "Flöden · Utkast" })
        .getByRole("link", { name: draft, exact: true })
    ).toBeVisible();
  }
);

test.describe("on a phone", () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true });

  test(
    "shows published flows apart from drafts in rows a thumb can open, without scrolling sideways",
    { tag: "@vite" },
    async ({ page }) => {
      test.setTimeout(120_000);
      const { list, draft } = await listedFlows(page);
      await page.goto(list);
      const { published, drafts } = groups(page);
      await expect(page.getByRole("table")).toHaveCount(0);
      await expect(published.getByRole("link")).toHaveCount(1);
      await expect(published.getByText("Indata: Ljud")).toBeVisible();
      await expect(drafts.getByRole("link", { name: new RegExp(draft) })).toBeVisible();
      // Two flows need no search on a phone: it would only take room from the rows.
      await expect(search(page)).toHaveCount(0);

      // Every row (its link covers it) and each group's toggle is a 44 px target, and the page
      // fits 320 px.
      for (const target of [
        published.getByRole("listitem"),
        drafts.getByRole("listitem"),
        published.getByRole("button", { name: "Publicerad", exact: true }),
        drafts.getByRole("button", { name: "Utkast", exact: true })
      ]) {
        const box = await target.boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true);

      const fold = drafts.getByRole("button", { name: "Utkast", exact: true });
      await fold.tap();
      await expect(fold).toHaveAttribute("aria-expanded", "false");
      await expect(drafts.getByRole("link")).toBeHidden();
      await fold.tap();
      await drafts.getByRole("link", { name: new RegExp(draft) }).tap();
      await expect(page).toHaveURL(new RegExp(`${list}/[^/]+$`));
    }
  );
});
