import { expect, test } from "@playwright/test";
import { askChatQuestion, conversationLog, MOCK_REPLY, uniqueName } from "./helpers";

test("personal chat streams an answer and reloads the saved session", async ({ page }) => {
  const question = uniqueName("e2e chat round-trip");

  await page.goto("/spaces/personal/chat");
  await askChatQuestion(page, question);

  // Scoped to the message list: the header shows the conversation title, which
  // can repeat the question or the mock answer once the title is generated.
  const log = conversationLog(page);
  await expect(log.getByText(question, { exact: true })).toBeVisible();
  await expect(log.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });

  const sessionId = new URL(page.url()).searchParams.get("session_id");
  expect(sessionId).toBeTruthy();

  await page.reload();
  await expect(log.getByText(question, { exact: true })).toBeVisible();
  await expect(log.getByText(MOCK_REPLY)).toBeVisible();
});
