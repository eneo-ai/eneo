import { expect, test } from "./csp";
import { uniqueName } from "./helpers";

test("creates a shared space and opens the knowledge collection flow", async ({ page }) => {
  const spaceName = uniqueName("E2E Knowledge Space");

  await page.goto("/spaces/list");
  // Scoped to the page: the app navigation may offer its own "Skapa yta".
  await page
    .getByRole("main")
    .getByRole("button", { name: /skapa yta|create space/i })
    .first()
    .click();
  const createDialog = page.getByRole("dialog");
  await createDialog.getByLabel(/namn|name/i).fill(spaceName);
  await createDialog.getByRole("button", { name: /skapa yta|create space/i }).click();

  await page.waitForURL(/\/spaces\/[^/]+\/overview$/, { timeout: 15_000 });
  // The space header: the space name is the overview's h1.
  await expect(page.getByRole("heading", { level: 1, name: spaceName })).toBeVisible();

  const overviewUrl = new URL(page.url());
  await page.goto(`${overviewUrl.pathname.replace(/\/overview$/, "/knowledge")}`);

  // Tab pages sit under the space name: "Kunskap" is the h2.
  await expect(
    page.getByRole("heading", { level: 2, name: /^(kunskap|knowledge)$/i })
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: /samlingar|collections/i })).toBeVisible();

  await page.getByRole("button", { name: /skapa samling|create collection/i }).click();
  const collectionDialog = page.getByRole("dialog");
  await expect(collectionDialog).toBeVisible();
  await expect(collectionDialog.getByLabel(/namn|name/i)).toBeVisible();
});
