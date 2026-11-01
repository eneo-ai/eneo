import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { apiPost, createSpace, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

// The platform layer of a touch screen (globals.css 14c): a text field is
// 16 px, or iOS Safari zooms into it on focus and stays zoomed; a control
// skips double-tap zoom; a 404 in the shell does not make the panel scroll.

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const NOT_TEXT = ["checkbox", "radio", "range", "file", "hidden", "color", "button", "submit"];

/** Visible text fields below 16 px, and visible controls that still take double-tap zoom. */
async function platformFaults(page: Page, screen: string) {
  return page.evaluate(
    ({ notText, screen }) => {
      const shown = (element: Element) => element.getClientRects().length > 0;
      const faults: string[] = [];
      for (const field of document.querySelectorAll(
        "input, textarea, select, [contenteditable='true']"
      )) {
        if (!shown(field) || notText.includes((field as HTMLInputElement).type)) continue;
        const size = parseFloat(getComputedStyle(field).fontSize);
        if (size < 16)
          faults.push(
            `${screen}: ${field.tagName} ${size}px ${field.id || field.getAttribute("name") || field.getAttribute("aria-label") || ""}`
          );
      }
      const controls =
        "a[href], button, input, select, textarea, [role=tab], [role=menuitem], [role=option]";
      for (const control of document.querySelectorAll(controls)) {
        if (!shown(control)) continue;
        if (getComputedStyle(control).touchAction === "auto") {
          faults.push(
            `${screen}: ${control.tagName} touch-action auto ${(control.textContent ?? "").trim().slice(0, 30)}`
          );
        }
      }
      return faults;
    },
    { notText: NOT_TEXT, screen }
  );
}

async function assistantEditor(page: Page) {
  const space = await createSpace(page, uniqueName("Platform"));
  const id = await apiPost(page, `/spaces/${space.split("/").pop()}/applications/assistants/`, {
    name: uniqueName("Bygglov")
  });
  return { space, editor: `${space}/assistants/${id}/edit` };
}

test(
  "text fields are 16 px and controls skip double-tap zoom, screen by screen",
  { tag: "@vite" },
  async ({ page }) => {
    const { space, editor } = await assistantEditor(page);
    const faults: string[] = [];
    const open = async (path: string) => {
      await page.goto(path);
      await expect(page.locator("main h1, [data-own-mobile-header]").first()).toBeVisible();
      faults.push(...(await platformFaults(page, path)));
    };

    for (const path of [
      "/dashboard",
      "/spaces/list",
      "/admin/users",
      "/spaces/personal/chat",
      `${space}/members`,
      `${space}/skills/new`
    ]) {
      await open(path);
    }

    // Every section of the editor: instructions, model settings, knowledge, API keys, ...
    await page.goto(editor);
    await expect(page.locator("[data-editor-row]").first()).toBeVisible();
    const ids = await page
      .locator("[data-editor-row]")
      .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-editor-row")!));
    expect(ids.length).toBeGreaterThan(5);
    for (const id of ids) await open(`${editor}?section=${id}`);

    // The palette and the create-space dialog hold fields of their own.
    await page.goto("/spaces/list");
    const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
    await expect(async () => {
      await page.keyboard.press("ControlOrMeta+k");
      await expect(palette).toBeVisible({ timeout: 1_000 });
    }).toPass({ timeout: 15_000 });
    faults.push(...(await platformFaults(page, "palette")));

    expect(faults).toEqual([]);
  }
);

test(
  "a page that does not exist fills the shell's panel without scrolling it",
  { tag: "@vite" },
  async ({ page }) => {
    for (const size of [
      { width: 390, height: 844 },
      { width: 820, height: 1180 },
      { width: 1280, height: 800 }
    ]) {
      await page.setViewportSize(size);
      await page.goto("/nothing-here-at-all");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(() => {
        const main = document.getElementById("main-content")!;
        return {
          panel: main.scrollHeight - main.clientHeight,
          page: document.documentElement.scrollHeight - document.documentElement.clientHeight
        };
      });
      expect(overflow, `at ${size.width} px`).toEqual({ panel: 0, page: 0 });
    }
  }
);

test(
  "the page's bars give way while a field has the focus on a very short screen",
  { tag: "@vite" },
  async ({ page }) => {
    // A phone turned sideways with its keyboard up leaves 50 to 150 px; 280 px is
    // a browser's own bars on a turned phone, short enough for the same rule.
    await page.setViewportSize({ width: 667, height: 280 });
    await page.goto("/spaces/list");
    const topBar = page.locator("header:not(main *)");
    await expect(topBar).toBeVisible();

    const filter = page.getByRole("textbox", { name: /^Filtrera / });
    await filter.focus();
    await expect(topBar).toBeHidden();
    await expect(filter).toBeInViewport();

    await filter.blur();
    await expect(topBar).toBeVisible();

    // A taller screen keeps its bar while typing.
    await page.setViewportSize({ width: 667, height: 420 });
    await filter.focus();
    await expect(topBar).toBeVisible();
  }
);
