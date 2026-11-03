import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { apiPost, createSpace, platformFaults, uniqueName } from "./helpers";

/** A new space with one assistant (or app); returns the space's path and the editor's. */
async function assistantEditor(page: Page, kind: "assistants" | "apps" = "assistants") {
  const space = await createSpace(page, uniqueName("Editor"));
  const name = uniqueName("Bygglov");
  const id = await apiPost(page, `/spaces/${space.split("/").pop()}/applications/${kind}/`, {
    name
  });
  return { space, name, editor: `${space}/${kind}/${id}/edit` };
}

test.describe("an editor on a phone (decision 21)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("opens on an index; a section opens in place and Back keeps what was typed", async ({
    page
  }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);

    const index = page.getByRole("navigation", { name: "Avsnitt" });
    const instructions = index.getByRole("link", { name: /^Instruktioner/ });
    await expect(instructions).toBeVisible();
    expect((await instructions.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    // The tablet's tab strip and section cards are not shown.
    await expect(page.locator("[data-editor-section]").first()).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );

    await instructions.click();
    await expect(page).toHaveURL(/\?section=instructions$/);
    const prompt = page.locator("#assistant-prompt");
    await expect(prompt).toBeVisible();
    await expect(index).toBeHidden();
    await prompt.fill("Svara kort på frågor om bygglov.");

    const bar = page.locator("[data-phone-page-bar]");
    await bar.getByRole("link", { name: /^Tillbaka till / }).click();
    await expect(page).not.toHaveURL(/section=/);
    await expect(instructions).toBeVisible();
    await expect(instructions).toBeFocused();
    await instructions.click();
    await expect(prompt).toHaveValue("Svara kort på frågor om bygglov.");
    // The system back returns to the index too.
    await page.goBack();
    await expect(instructions).toBeVisible();
    await expect(prompt).toBeHidden();
  });

  test("opens a section from its address, after a reload too", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(`${editor}?section=ai`);
    await expect(page.locator('[data-editor-section="ai"]')).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Avsnitt" })).toBeHidden();
    await page.reload();
    await expect(page.locator('[data-editor-section="ai"]')).toBeVisible();
  });

  test("a new assistant opens on General with its name selected", async ({ page }) => {
    const space = await createSpace(page, uniqueName("Create"));
    await page.goto(`${space}/assistants`);
    await page.getByRole("main").getByRole("button", { name: "Skapa assistent" }).click();
    await page.waitForURL(/\/edit$/);

    const name = page.locator("#assistant-name");
    await expect(name).toBeVisible();
    await expect(name).toBeFocused();
    expect(
      await name.evaluate(
        (input: HTMLInputElement) =>
          input.selectionStart === 0 && input.selectionEnd === input.value.length
      )
    ).toBe(true);
  });
});

test.describe("an editor on a small phone", () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true });

  for (const kind of ["assistants", "apps"] as const) {
    test(`fits every section of ${kind} in 320 px, nothing scrolling sideways`, async ({
      page
    }) => {
      // Every section of an editor in one test (15-22 s on CI): a budget for its work.
      test.setTimeout(90_000);
      const { editor } = await assistantEditor(page, kind);
      await page.goto(editor);
      await expect(page.locator("[data-editor-row]").first()).toBeVisible();
      const ids = await page
        .locator("[data-editor-row]")
        .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-editor-row")!));
      expect(ids.length).toBeGreaterThan(5);
      for (const id of ids) {
        await page.goto(`${editor}?section=${id}`);
        await expect(page.locator(`[data-editor-section="${id}"]`)).toBeVisible();
        // The touch platform layer (touch-platform.spec.ts) holds in every section too.
        expect(await platformFaults(page, `section ${id}`)).toEqual([]);
        const overflow = await page.evaluate(() => {
          const main = document.getElementById("main-content")!;
          return main.scrollWidth - main.clientWidth;
        });
        expect(overflow, `section ${id}`).toBeLessThanOrEqual(0);
        if (id === "api-keys") {
          const tabs = page.getByRole("tablist", { name: "API-nycklar" }).getByRole("tab");
          await tabs.first().focus();
          await page.keyboard.press("End");
          await expect(tabs.last()).toBeFocused();
          await page.keyboard.press("Enter");
          await expect(tabs.last()).toHaveAttribute("aria-selected", "true");
          await expect(tabs.last()).toBeInViewport();
        }
      }
    });
  }
});

test.describe("a page bar's back link", () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true });

  test("always names its parent; a name too long for the bar ends in an ellipsis and the link's name holds all of it", async ({
    page
  }) => {
    const { editor, name } = await assistantEditor(page);
    await page.goto(`${editor}?section=security`);
    const back = page.locator("[data-phone-page-bar] a").first();
    const widths = [320, 324, 328, 332, 340, 360, 375, 390, 414, 430];
    const cutAt: number[] = [];
    for (const width of [...widths, ...widths.toReversed()]) {
      await page.setViewportSize({ width, height: 640 });
      // The full name is reachable by assistive technology at every width (ACCESSIBILITY.md 6).
      await expect(back).toHaveAccessibleName(`Tillbaka till ${name}`);
      // Measured after the resize: the label is the parent's whole name, and a label cut
      // for room ends in an ellipsis; nothing else in the link is cut.
      await expect
        .poll(() =>
          back.evaluate((link, parent) => {
            const parts = [link, ...link.querySelectorAll<HTMLElement>("*")];
            const label = parts.find(
              (element) => element.childElementCount === 0 && element.textContent === parent
            );
            if (!label) return "no label with the parent's name";
            const cut = (element: Element) => element.scrollWidth > element.clientWidth + 1;
            if (cut(label) && getComputedStyle(label).textOverflow !== "ellipsis")
              return "cut without an ellipsis";
            if (
              parts.some((element) => element !== label && !element.contains(label) && cut(element))
            )
              return "another part is cut";
            return cut(label) ? "ellipsis" : "whole";
          }, name)
        )
        .toMatch(/^(ellipsis|whole)$/);
      if (
        await back.evaluate((link) =>
          [...link.querySelectorAll("*")].some(
            (element) =>
              element.childElementCount === 0 && element.scrollWidth > element.clientWidth + 1
          )
        )
      )
        cutAt.push(width);
    }
    // The name is long enough to need the ellipsis on the narrowest phone.
    expect(cutAt).toContain(320);
  });
});

test.describe("an editor on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keeps the section strip and every section on one page", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    await expect(page.getByRole("navigation", { name: "Avsnitt", exact: true })).toBeVisible();
    await expect(page.locator("[data-editor-index]")).toBeHidden();
    await expect(page.locator("[data-phone-page-bar]")).toBeHidden();
    for (const id of ["general", "instructions", "ai"]) {
      await expect(page.locator(`[data-editor-section="${id}"]`)).toBeVisible();
    }
  });
});

test.describe("an editor turned across 768 px", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keeps focus on what it was on, or on its counterpart, both ways", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    // A tablet, typing in Instruktioner; narrowed to a phone, the field's
    // section opens in place with the field still focused.
    const prompt = page.locator("#assistant-prompt");
    await prompt.fill("Svara kort.");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page).toHaveURL(/\?section=instructions$/);
    await expect(prompt).toBeVisible();
    await expect(prompt).toBeFocused();
    await expect(prompt).toHaveValue("Svara kort.");

    // A phone's index row, widened to a tablet: its section's heading.
    await page
      .locator("[data-phone-page-bar]")
      .getByRole("link", { name: /^Tillbaka till / })
      .click();
    const row = page.getByRole("navigation", { name: "Avsnitt" }).getByRole("link", {
      name: /^Instruktioner/
    });
    await expect(row).toBeFocused();
    await page.setViewportSize({ width: 820, height: 1180 });
    const heading = page
      .locator('[data-editor-section="instructions"]')
      .getByRole("heading")
      .first();
    await expect(heading).toBeVisible();
    await expect(heading).toBeFocused();
  });
});

test.describe("an editor turned while a section is open from the index", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("keeps Back and Forward as they were", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    const index = page.getByRole("navigation", { name: "Avsnitt" });
    await index.getByRole("link", { name: /^Allmänt/ }).click();
    await expect(page).toHaveURL(/\?section=general$/);

    // Widened, the prompt in Instruktioner takes focus; narrowed, its section
    // replaces Allmänt in the same history entry.
    await page.setViewportSize({ width: 820, height: 1180 });
    const prompt = page.locator("#assistant-prompt");
    await prompt.focus();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page).toHaveURL(/\?section=instructions$/);
    await expect(prompt).toBeFocused();

    // The bar's Back pops that entry to the index; Forward brings it back.
    await page
      .locator("[data-phone-page-bar]")
      .getByRole("link", { name: /^Tillbaka till / })
      .click();
    await expect(page).not.toHaveURL(/section=/);
    await expect(index.getByRole("link", { name: /^Instruktioner/ })).toBeFocused();
    await page.goForward();
    await expect(page).toHaveURL(/\?section=instructions$/);
    await expect(prompt).toBeVisible();
  });
});

/**
 * Makes the editor's sticky header taller, as a long title wrapping to two lines would,
 * and waits until the section's scroll margin has followed it.
 */
async function growHeader(page: Page, section: string) {
  const header = page.locator("[data-space-full-bleed] > header");
  await header.evaluate((element) =>
    (element.firstElementChild as HTMLElement).style.setProperty("padding-bottom", "48px")
  );
  await expect
    .poll(async () => {
      const { height } = (await header.boundingBox())!;
      const margin = await page
        .locator(`[id="${section}"]`)
        .evaluate((element) => parseFloat(getComputedStyle(element).scrollMarginTop));
      return margin - height;
    })
    .toBeGreaterThanOrEqual(0);
}

/** The section's own top (the anchor's target, not a heading inset in it) is clear of the header. */
async function expectBelowHeader(page: Page, section: string) {
  const target = page.locator(`[id="${section}"]`);
  await expect(target).toBeInViewport();
  await expect
    .poll(async () => {
      const header = (await page.locator("[data-space-full-bleed] > header").boundingBox())!;
      return (await target.boundingBox())!.y - (header.y + header.height);
    })
    .toBeGreaterThanOrEqual(-0.5);
}

test.describe("an editor on a laptop", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("lists every section beside the form, under its group, and keeps the list in view", async ({
    page
  }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    const list = page.getByRole("navigation", { name: "Avsnitt", exact: true });
    await expect(list).toHaveAttribute("data-editor-rail");
    await expect(page.locator("header").getByRole("navigation", { name: "Avsnitt" })).toBeHidden();
    for (const group of ["Innehåll", "Modell och funktioner", "Åtkomst"]) {
      await expect(list.getByRole("group", { name: group })).toBeVisible();
    }
    for (const name of ["Allmänt", "Bilagor", "Säkerhet och integritet", "Publicering"]) {
      await expect(list.getByRole("link", { name })).toBeVisible();
    }

    // A link scrolls its section to just below the sticky header, however tall the header
    // grows; the list stays where it was.
    await growHeader(page, "security");
    const top = (await list.boundingBox())!.y;
    await list.getByRole("link", { name: "Säkerhet och integritet" }).click();
    await expectBelowHeader(page, "security");
    expect(Math.abs((await list.boundingBox())!.y - top)).toBeLessThanOrEqual(1);
  });
});

test.describe("an editor on an iPad held sideways", () => {
  test.use({ viewport: { width: 1180, height: 820 }, hasTouch: true });

  test("reaches the list's last section", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    const list = page.locator("[data-editor-rail]");
    const last = list.getByRole("link").last();
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
  });

  test("lines space settings up with the space's header", async ({ page }) => {
    const space = await createSpace(page, uniqueName("Settings"));
    await page.goto(`${space}/settings`);
    const list = page.locator("[data-editor-rail]");
    await expect(list).toBeVisible();
    // The space's header: its breadcrumbs start on the frame's line.
    const crumbs = page.locator("main header nav").first();
    const line = (await crumbs.boundingBox())!.x;
    const first = list.getByRole("link").first();
    expect(Math.abs((await first.boundingBox())!.x - line)).toBeLessThanOrEqual(1);
    const title = page.locator("[data-space-full-bleed] > header").getByRole("heading").first();
    expect(Math.abs((await title.boundingBox())!.x - line)).toBeLessThanOrEqual(1);
  });
});

test.describe("an editor on a tablet, at the card's height", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("scrolls a section from the strip to just below the header", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    const strip = page.locator("header").getByRole("navigation", { name: "Avsnitt" });
    await growHeader(page, "ai");
    await strip.getByRole("link", { name: "AI-inställningar" }).click();
    await expectBelowHeader(page, "ai");
  });
});

test.describe("an unavailable Promptguide", () => {
  /** Opens the editor's instructions with the Promptguide reported unavailable. */
  async function openInstructions(page: Page, section: string) {
    const { editor } = await assistantEditor(page);
    // The real answer, so it keeps the session's headers; only its body says unavailable.
    await page.route("**/api/v1/help-assistants/availability**", async (route) =>
      route.fulfill({
        response: await route.fetch(),
        json: { available: false, disabled_reason: "no_assignment" }
      })
    );
    const availability = page.waitForResponse("**/api/v1/help-assistants/availability**");
    await page.goto(`${editor}${section}`);
    await availability;
    await expect(page.getByRole("button", { name: "Visa prompthistorik" })).toBeVisible();
    return page.getByRole("button", { name: "Promptguide", includeHidden: true });
  }

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

    test("is left out, as its reason's tooltip cannot be reached", async ({ page }) => {
      const promptGuide = await openInstructions(page, "?section=instructions");
      await expect(promptGuide).toBeAttached();
      await expect(promptGuide).toBeHidden();
    });
  });

  test.describe("on a tablet", () => {
    test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

    test("is shown disabled, its reason in the tooltip", async ({ page }) => {
      const promptGuide = await openInstructions(page, "");
      await expect(promptGuide).toBeVisible();
      await expect(promptGuide).toBeDisabled();
    });
  });
});
