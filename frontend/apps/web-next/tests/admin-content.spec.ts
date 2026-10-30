import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";
import { apiPost } from "./helpers";

for (const [path, heading] of [
  ["/admin/prompt-library", messages.governance_tab_prompts],
  ["/admin/personal-assistant", messages.governance_title],
  ["/admin/skills", messages.admin_skills_title],
  ["/admin/help-assistants", messages.admin_help_assistants_page_title]
] as const) {
  test(`opens admin content at ${path}`, { tag: "@vite" }, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
  });
}

test(
  "template administration follows the saved tenant setting",
  { tag: "@vite" },
  async ({ page }) => {
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
  }
);

test("opens an installed helper in the organization editor", { tag: "@vite" }, async ({ page }) => {
  await page.goto("/admin/help-assistants");
  await apiPost(page, "/admin/help-assistants/roles/prompt_guide/", {});
  try {
    await page.goto("/admin/help-assistants/prompt_guide");
    await expect(
      page.getByRole("heading", { level: 1, name: "Prompt Guide", exact: true })
    ).toBeVisible();
    await expect(
      page.getByText(messages.admin_help_assistants_edit_banner, { exact: true })
    ).toBeVisible();
  } finally {
    await page.goto("/admin/help-assistants");
    await page
      .getByRole("button", { name: messages.admin_help_assistants_delete_button, exact: true })
      .click();
    const dialog = page.getByRole("alertdialog", {
      name: messages.admin_help_assistants_delete_button,
      exact: true
    });
    await dialog
      .getByRole("button", { name: messages.admin_help_assistants_delete_button, exact: true })
      .click();
    await expect(dialog).toBeHidden();
  }
});

test("an unknown helper kind shows not-found", { tag: "@vite" }, async ({ page }) => {
  test.skip(!process.env.E2E_BASE_URL, "Unknown helper kinds are rejected by the Vite route.");
  await page.goto("/admin/help-assistants/unknown-kind");
  await expect(
    page.getByRole("heading", { level: 1, name: messages.page_not_found, exact: true })
  ).toBeVisible();
});
