import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * Key hints (⌘ ↵ beside Send, ⌘K in the menu and the palette's footer) point at keys.
 * A touch screen has none, and a phone-width window with a mouse (a desktop browser
 * narrowed to the phone layout, the way a developer or a split view looks at it) has no
 * room for them: they crowd the send button. From the laptop layout up, with a mouse, the
 * composer still shows its hint, so hiding must not go too far.
 */

/** The visible key hints in the document, or only in what `within` selects. */
const visibleKeyHints = (page: import("@playwright/test").Page, within?: string) =>
  page.evaluate(
    (scope) =>
      [...(scope ? document.querySelectorAll(scope) : [document]).values()].flatMap((root) =>
        [...root.querySelectorAll("kbd")]
          .filter((key) => key.getClientRects().length > 0)
          .map((key) => (key.textContent ?? "").trim())
      ),
    within
  );

for (const touch of [true, false]) {
  test(
    `no key hints in a phone-width window ${touch ? "on a touch screen" : "with a mouse"}`,
    { tag: ["@vite", "@key-hints"] },
    async ({ browser, baseURL }) => {
      const context = await browser.newContext({
        baseURL,
        storageState: STORAGE_STATE,
        viewport: { width: 390, height: 844 },
        hasTouch: touch,
        isMobile: touch
      });
      const page = await context.newPage();
      await page.goto("/spaces/personal/chat");
      await expect(page.getByRole("textbox", { name: /^Fråga / })).toBeVisible();
      expect(await visibleKeyHints(page), "the composer").toEqual([]);

      await page.getByRole("button", { name: "Öppna meny" }).click();
      await expect(page.getByRole("link", { name: "Assistenter" }).first()).toBeVisible();
      expect(await visibleKeyHints(page), "the menu").toEqual([]);
      await page.keyboard.press("Escape");

      await page.keyboard.press("Control+k");
      await expect(page.getByRole("combobox").first()).toBeVisible();
      expect(await visibleKeyHints(page), "the command palette").toEqual([]);
      await context.close();
    }
  );
}

test(
  "the composer keeps its key hint in the laptop layout with a mouse",
  { tag: ["@vite", "@key-hints"] },
  async ({ browser, baseURL }) => {
    const context = await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      viewport: { width: 1280, height: 800 }
    });
    const page = await context.newPage();
    await page.goto("/spaces/personal/chat");
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toBeVisible();
    // In the composer itself: the menu's own ⌘K hint is also on screen at this width and
    // would keep this green if the composer's went missing.
    expect((await visibleKeyHints(page, "[data-start-composer]")).length).toBeGreaterThan(0);
    await context.close();
  }
);
