import { expect, test } from "@playwright/test";
import { uniqueName } from "./helpers";

test("creates a shared space and opens the knowledge collection flow", async ({ page }) => {
  const spaceName = uniqueName("E2E Knowledge Space");

  await page.goto("/spaces/list");
  await page
    .getByRole("button", { name: /skapa yta|create space/i })
    .first()
    .click();
  await page.getByLabel(/namn|name/i).fill(spaceName);
  await page
    .getByRole("button", { name: /skapa yta|create space/i })
    .last()
    .click();

  await page.waitForURL(/\/spaces\/[^/]+\/overview$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: spaceName })).toBeVisible();

  const overviewUrl = new URL(page.url());
  await page.goto(`${overviewUrl.pathname.replace(/\/overview$/, "/knowledge")}`);

  await expect(page.getByRole("heading", { name: /kunskap|knowledge/i })).toBeVisible();
  await expect(page.getByRole("tab", { name: /samlingar|collections/i })).toBeVisible();

  await page.getByRole("button", { name: /skapa samling|create collection/i }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByLabel(/namn|name/i)).toBeVisible();
});
