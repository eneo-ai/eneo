import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { createFixtures, openRoute } from "./responsive-fixtures";
import { ROUTES, type Fixtures } from "./responsive-routes";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * The turn-and-resize contract: a phone turned, an iPad split or a window dragged
 * crosses 768 px with something open, and nothing may be lost or swapped. Every
 * dialog that a screen's create-style buttons open is opened on a phone, a field in
 * it is filled and focused, and the viewport crosses 768 px and comes back. The dialog
 * is still open, the field is the very same element (a remount drops the mark set
 * on it), holds what was typed and keeps focus. This is the biggest class of real
 * bug found in the responsive pass: a layout that swaps a component at a breakpoint
 * rebuilds it, and a recording or a half-typed form is gone.
 *
 * CONTRACT_ROUTES=<regexp> narrows the routes; a route with no such button is skipped.
 */

const PHONE = { width: 390, height: 844 };
const CROSSINGS = [
  { name: "an iPad portrait", width: 820, height: 1180 },
  { name: "a desktop", width: 1280, height: 800 }
];
const OPENERS = /^(skapa|ny|nytt|ny |lägg till|bjud in|importera|create|new|add|invite|import)\b/i;
const MARK = "data-turn-mark";

let fixtures: Fixtures;
test.beforeAll(async ({ browser, baseURL }) => {
  fixtures = await createFixtures(browser, baseURL, "Turn");
});

/** The names of the buttons on the screen that are likely to open a form dialog. */
async function openerNames(page: Page): Promise<string[]> {
  const names = await page
    .getByRole("main")
    .getByRole("button")
    .evaluateAll((buttons) =>
      buttons.map((button) =>
        (button.getAttribute("aria-label") ?? button.textContent ?? "").trim()
      )
    );
  return [...new Set(names.filter((name) => OPENERS.test(name)))].slice(0, 3);
}

test(
  "a dialog's field survives crossing 768 px and back",
  { tag: ["@vite", "@turn"] },
  async ({ browser, baseURL }) => {
    test.setTimeout(15 * 60_000);
    const context = await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      viewport: PHONE,
      hasTouch: true,
      isMobile: true
    });
    const page = await context.newPage();
    const problems: string[] = [];
    let opened = 0;
    const covered: string[] = [];

    for (const [pattern, entry] of Object.entries(ROUTES)) {
      if ("skip" in entry || entry.auth === "out") continue;
      if (process.env.CONTRACT_ROUTES && !new RegExp(process.env.CONTRACT_ROUTES).test(pattern))
        continue;
      try {
        await openRoute(page, entry.url(fixtures), true);
      } catch {
        continue; // the contract reports a screen that does not open
      }
      for (const name of await openerNames(page)) {
        await page.setViewportSize(PHONE);
        await openRoute(page, entry.url(fixtures), true);
        const opener = page.getByRole("main").getByRole("button", { name, exact: true }).first();
        if (!(await opener.isVisible().catch(() => false))) continue;
        await opener.click();
        const dialog = page.getByRole("dialog").last();
        if (!(await dialog.isVisible({ timeout: 1500 }).catch(() => false))) continue;
        const field = dialog
          .locator("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea")
          .first();
        if (!(await field.isVisible().catch(() => false))) {
          await page.keyboard.press("Escape");
          continue;
        }
        opened++;
        const where = `${pattern} › ${name}`;
        covered.push(where);
        await field.evaluate((element, mark) => element.setAttribute(mark, "1"), MARK);
        await field.fill("Tur och retur");
        await field.focus();
        for (const size of [...CROSSINGS, { name: "the phone again", ...PHONE }]) {
          await page.setViewportSize({ width: size.width, height: size.height });
          await page.waitForTimeout(300);
          const marked = page.locator(`[${MARK}]`);
          if ((await marked.count()) !== 1) {
            problems.push(`${where}: the field was rebuilt at ${size.name}`);
            break;
          }
          if (!(await dialog.isVisible()))
            problems.push(`${where}: the dialog closed at ${size.name}`);
          if ((await marked.inputValue().catch(() => "")) !== "Tur och retur")
            problems.push(`${where}: what was typed is gone at ${size.name}`);
          if (!(await marked.evaluate((element) => element === document.activeElement)))
            problems.push(`${where}: focus left the field at ${size.name}`);
        }
        await page.keyboard.press("Escape");
      }
    }
    await context.close();
    test.info().annotations.push({ type: "dialogs", description: covered.join("; ") });
    console.log(`turn-and-resize covered ${opened} dialogs: ${covered.join("; ")}`);
    expect(problems, problems.join("\n")).toEqual([]);
    // A narrowed run (CONTRACT_ROUTES) opens few; the whole run must still find its dialogs.
    if (!process.env.CONTRACT_ROUTES)
      expect(opened, "no dialog was opened: the opener pattern found nothing").toBeGreaterThan(5);
  }
);
