import { expect, test } from "@playwright/test";
import { askChatQuestion, MOCK_REPLY, uniqueName } from "./helpers";

test("chat recovers after the provider returns an error", async ({ page }) => {
  await page.goto("/spaces/personal/chat");

  const failedQuestion = `${uniqueName("e2e forced failure")} E2E_FORCE_MODEL_ERROR`;
  await askChatQuestion(page, failedQuestion);

  await expect(page.getByRole("alert").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[contenteditable="true"]').first()).toContainText(failedQuestion);

  const recoveryQuestion = uniqueName("e2e recovery ping");
  await askChatQuestion(page, recoveryQuestion);

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText(recoveryQuestion, { exact: true })).toBeVisible();
  await expect(page.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
});
