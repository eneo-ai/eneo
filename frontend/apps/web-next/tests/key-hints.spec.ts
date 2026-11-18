import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";

/*
 * Key hints (⌘K in the menu and the palette's footer) point at keys. A touch screen has
 * none, and a phone-width window with a mouse (a desktop browser narrowed to the phone
 * layout, the way a developer or a split view looks at it) has no room for them. Send's
 * keys are on its tooltip, where a mouse finds them without crowding the composer's row.
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
    { tag: "@key-hints" },
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
  "Send names its keys on its tooltip in the laptop layout with a mouse",
  { tag: "@key-hints" },
  async ({ browser, baseURL }) => {
    const context = await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      viewport: { width: 1280, height: 800 }
    });
    const page = await context.newPage();
    // Send moves twice after the field shows, and a pointer it leaves closes the tooltip: the
    // lists below the composer recentre it once both have answered, and the context meter adds
    // a line under it.
    const lists = ["/api/v1/conversations/recent/", "/api/v1/dashboard/"].map((path) =>
      page.waitForResponse((response) => new URL(response.url()).pathname === path)
    );
    await page.goto("/spaces/personal/chat");
    await Promise.all(lists);
    const composer = page.locator("[data-start-composer]");
    await expect(composer.getByRole("button", { name: /^Kontextanvändning/ })).toBeVisible();
    await composer.getByRole("button", { name: "Skicka meddelande" }).hover();
    await expect(page.getByText("Skicka (Retur). Skift+Retur ger en ny rad.")).toBeVisible();
    await context.close();
  }
);

test(
  "Shift+Return adds a line with a mouse, and Return adds one on a touch screen",
  { tag: "@key-hints" },
  async ({ browser, baseURL }) => {
    for (const touch of [false, true]) {
      const context = await browser.newContext({
        baseURL,
        storageState: STORAGE_STATE,
        viewport: touch ? { width: 820, height: 1180 } : { width: 1280, height: 800 },
        hasTouch: touch,
        isMobile: touch
      });
      const page = await context.newPage();
      await page.goto("/spaces/personal/chat");
      const field = page.getByRole("textbox", { name: /^Fråga / });
      await field.fill("a");
      // Return itself sends with a mouse (unit-tested): nothing is sent here.
      await field.press(touch ? "Enter" : "Shift+Enter");
      await expect(field).toHaveValue("a\n");
      await expect(page.getByRole("log")).toHaveCount(0);
      await context.close();
    }
  }
);
