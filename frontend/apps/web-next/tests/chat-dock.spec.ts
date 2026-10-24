import { expect, test } from "./csp";
import { askChatQuestion, chatComposer, conversationLog, MOCK_REPLY, uniqueName } from "./helpers";

// A phone on its side, or with the keyboard up: the docked composer takes at
// most two thirds of the height (conversation-layout.tsx), so a long draft
// never leaves the conversation without room, and Send stays reachable.
test.use({ viewport: { width: 390, height: 320 }, hasTouch: true, isMobile: true });

test("a long draft leaves room for the conversation and keeps Send reachable", async ({ page }) => {
  await page.goto("/spaces/personal/chat");
  await askChatQuestion(page, uniqueName("e2e dock"));
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });

  const lines = Array.from({ length: 14 }, (_, line) => `Rad ${line + 1} i ett långt utkast`);
  await chatComposer(page).fill(lines.join("\n"));

  // The conversation's own scroll box keeps a usable height.
  const conversationHeight = await conversationLog(page).evaluate((log) => {
    let box: HTMLElement | null = log.parentElement;
    while (box && getComputedStyle(box).overflowY !== "auto") box = box.parentElement;
    return box?.getBoundingClientRect().height ?? 0;
  });
  expect(conversationHeight).toBeGreaterThanOrEqual(64);

  const send = page.getByRole("button", { name: /^(Skicka meddelande|Send message)$/ });
  await send.scrollIntoViewIfNeeded();
  await expect(send).toBeInViewport();
  // The page panel itself never scrolls for it.
  expect(
    await page.locator("#main-content").evaluate((main) => main.scrollHeight - main.clientHeight)
  ).toBeLessThanOrEqual(1);
});
