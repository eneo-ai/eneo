import { expect, test } from "./csp";
import { createSpace, openCreateCollectionDialog, uniqueName } from "./helpers";

test("creates a shared space and opens the knowledge collection flow", async ({ page }) => {
  const spaceName = uniqueName("E2E Knowledge Space");
  const space = await createSpace(page, spaceName);
  // Översikt is the overview's h1; the space's name is the h2 under it.
  await expect(page.getByRole("heading", { level: 2, name: spaceName })).toBeVisible();

  await page.goto(`${space}/knowledge`);
  // Beside the sidebar each section's title is the page's h1, as in Svelte's page bar.
  await expect(
    page.getByRole("heading", { level: 1, name: /^(kunskap|knowledge)$/i })
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: /samlingar|collections/i })).toBeVisible();

  // The create dialog opens with its name field (the helper waits for it).
  await openCreateCollectionDialog(page);
});
