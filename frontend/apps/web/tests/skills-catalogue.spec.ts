import { expect, test } from "@playwright/test";

test("organisation Skills catalogue and create form are visible in the app shell", async ({
  page
}) => {
  await page.goto("/spaces/organization/skills");

  await expect
    .poll(async () => (await page.locator("#global-page-container").boundingBox())?.height ?? 0)
    .toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "Skills", level: 1 })).toBeVisible();

  await page
    .getByRole("link", {
      name: /^(Create Skill|Create the first Skill|Skapa skill|Skapa din första skill)$/
    })
    .first()
    .click();

  await expect(page).toHaveURL(/\/spaces\/organization\/skills\/new$/);
  await expect(
    page.getByRole("heading", { name: /^(Create Skill|Skapa skill)$/, level: 1 })
  ).toBeVisible();
  await expect(page.getByLabel(/^(Name|Namn)$/)).toBeVisible();
  await expect(page.getByLabel(/^(Description|Beskrivning)$/)).toBeVisible();
  await expect(page.getByLabel(/^(Instructions|Instruktioner)$/)).toBeVisible();
});
