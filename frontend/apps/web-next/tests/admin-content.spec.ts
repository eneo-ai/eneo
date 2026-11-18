import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";

for (const [path, heading] of [
  ["/admin/prompt-library", messages.governance_tab_prompts],
  ["/admin/personal-assistant", messages.governance_title],
  ["/admin/skills", messages.admin_skills_title],
  ["/admin/help-assistants", messages.admin_helper_title]
] as const) {
  test(`opens admin content at ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
  });
}

test("template administration follows the saved tenant setting", async ({ page }) => {
  await page.goto("/admin/settings");
  const toggle = page.getByRole("switch", { name: messages.enable_templates, exact: true });
  await expect(toggle).toBeVisible();
  const original = await toggle.isChecked();

  async function setTemplates(enabled: boolean) {
    await page.goto("/admin/settings");
    await expect(toggle).toBeVisible();
    if ((await toggle.isChecked()) === enabled) return;
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        response.url().endsWith("/api/v1/settings/templates")
    );
    await toggle.click();
    await expect(toggle).toBeChecked({ checked: enabled });
    expect((await saved).ok()).toBe(true);
  }

  try {
    await setTemplates(true);
    await page.goto("/admin/templates");
    await expect(
      page.getByRole("heading", { level: 1, name: messages.templates, exact: true })
    ).toBeVisible();
    await setTemplates(false);
    await page.goto("/admin/templates");
    await expect(page).toHaveURL(/\/admin\/?$/);
  } finally {
    await setTemplates(original);
  }
});

test("an unknown helper kind shows not-found", async ({ page }) => {
  await page.goto("/admin/help-assistants/unknown-kind");
  await expect(
    page.getByRole("heading", { level: 1, name: messages.page_not_found, exact: true })
  ).toBeVisible();
});
