import { expect, test } from "@playwright/test";

// Central flow #4: the core product loop. A logged-in user sends a message in the
// personal chat and gets the assistant's streamed answer. The seeded model points
// at the deterministic mock server, so the reply is always the same fixed string —
// this exercises the full chain (UI → conversations SSE → litellm → model) without
// touching a real provider.
test("sending a message streams the assistant's answer", async ({ page }) => {
  await page.goto("/spaces/personal/chat");

  const input = page.locator('[contenteditable="true"]').first();
  await input.click();
  await input.pressSequentially("ping");

  await page.locator('button[name="ask"]').click();

  await expect(page.getByText("E2E mock completion: pong")).toBeVisible({ timeout: 20_000 });
});
