import { expect, test } from "./csp";
import {
  addActivityToAnswers,
  askChatQuestion,
  chatComposer,
  conversationLog,
  MOCK_REPLY,
  uniqueName
} from "./helpers";

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

test.describe("an answer's sources on a phone (decision 28)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("open in a sheet that leaves the source and the answer readable above it", async ({
    page
  }) => {
    await addActivityToAnswers(page);
    await page.goto("/spaces/personal/chat");
    await askChatQuestion(page, uniqueName("e2e källor"));
    await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });

    const source = conversationLog(page)
      .getByRole("list", { name: /^(Källor|Sources)$/ })
      .getByRole("button", { name: /E2E-källa/ });
    await source.click();
    const sheet = page.getByRole("dialog", {
      name: /^(Aktivitet för svaret|Activity for the answer)$/
    });
    const tabs = sheet.getByRole("tablist");
    await expect(tabs).toBeVisible();
    // Not modal: the page behind stays readable and scrollable…
    await expect(sheet).not.toHaveAttribute("aria-modal", "true");
    // …and nothing it covers can take the focus (2.4.11): the dock gives way.
    await expect(chatComposer(page)).toBeHidden();
    // The source it was opened from stands above it.
    const sheetTop = (await tabs.boundingBox())!.y;
    const sourceBox = (await source.boundingBox())!;
    expect(sourceBox.y + sourceBox.height).toBeLessThanOrEqual(sheetTop);

    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(source).toBeFocused();
    await expect(chatComposer(page)).toBeVisible();
  });
});
