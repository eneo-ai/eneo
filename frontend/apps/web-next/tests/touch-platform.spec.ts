import { expect, test } from "./csp";
import { createSpace, platformFaults, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

// The platform layer of a touch screen (globals.css 14c): a text field is
// 16 px, or iOS Safari zooms into it on focus and stays zoomed; a control
// skips double-tap zoom; a 404 in the shell does not make the panel scroll.

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test(
  "text fields are 16 px and controls skip double-tap zoom, screen by screen",
  { tag: "@vite" },
  async ({ page }) => {
    // One test walks several screens: its budget is its work, not the 30 s a
    // single-screen test gets. An editor's sections are checked in editor-sections.spec.ts.
    test.setTimeout(90_000);
    const space = await createSpace(page, uniqueName("Platform"));
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
