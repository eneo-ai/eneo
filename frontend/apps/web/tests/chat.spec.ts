import { expect, test } from "@playwright/test";

// Central flow #4: the core product loop. A logged-in user sends a message in the
// personal chat and gets the assistant's streamed answer. The seeded model points
// at the deterministic mock server, so the reply is always the same fixed string —
// this exercises the full chain (UI → conversations SSE → litellm → model) without
// touching a real provider.
test("a streamed answer is saved and can be reopened from history", async ({ page }) => {
  await page.goto("/spaces/personal/chat");

  const question = "e2e persistence ping";
  const input = page.locator('[contenteditable="true"]').first();
  await input.click();
  await input.pressSequentially(question);

  await page.locator('button[name="ask"]').click();

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText("E2E mock completion: pong")).toBeVisible({ timeout: 20_000 });

  await page.getByRole("tablist").getByRole("tab").nth(1).click();

  const savedConversation = page.locator("table tbody button").first();
  await expect(savedConversation).toBeVisible();
  await savedConversation.click();

  const conversation = page.locator("#session-message-container");
  await expect(conversation.getByText(question, { exact: true })).toBeVisible();
  await expect(conversation.getByText("E2E mock completion: pong")).toBeVisible();

  await page.reload();

  await expect(conversation.getByText(question, { exact: true })).toBeVisible();
  await expect(conversation.getByText("E2E mock completion: pong")).toBeVisible();
});
