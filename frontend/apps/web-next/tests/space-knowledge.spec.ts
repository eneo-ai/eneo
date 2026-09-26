import { expect, test } from "./csp";
import { createSpace, openCreateCollectionDialog, uniqueName } from "./helpers";

test("creates a shared space and opens the knowledge collection flow", async ({ page }) => {
  const spaceName = uniqueName("E2E Knowledge Space");
  const space = await createSpace(page, spaceName);
  // The space header: the space name is the overview's h1.
  await expect(page.getByRole("heading", { level: 1, name: spaceName })).toBeVisible();

  await page.goto(`${space}/knowledge`);
  // Tab pages sit under the space name: "Kunskap" is the h2.
  await expect(
    page.getByRole("heading", { level: 2, name: /^(kunskap|knowledge)$/i })
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: /samlingar|collections/i })).toBeVisible();

  // The create dialog opens with its name field (the helper waits for it).
  await openCreateCollectionDialog(page);
});
