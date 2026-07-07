import { expect, test } from "@playwright/test";
import { askChatQuestion, MOCK_REPLY, uniqueName } from "./helpers";

test("personal chat streams an answer and reloads the saved session", async ({ page }) => {
  const question = uniqueName("e2e chat round-trip");

  await page.goto("/spaces/personal/chat");
  await askChatQuestion(page, question);

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });

  const sessionId = new URL(page.url()).searchParams.get("session_id");
  expect(sessionId).toBeTruthy();

  await page.reload();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText(MOCK_REPLY)).toBeVisible();
});
