import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { apiPost, createSpace, uniqueName } from "./helpers";

/** A new space with one assistant (or app); returns the space's path and the editor's. */
async function assistantEditor(page: Page, kind: "assistants" | "apps" = "assistants") {
  const space = await createSpace(page, uniqueName("Editor"));
  const id = await apiPost(page, `/spaces/${space.split("/").pop()}/applications/${kind}/`, {
    name: uniqueName("Bygglov")
  });
  return { space, editor: `${space}/${kind}/${id}/edit` };
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
      const { editor } = await assistantEditor(page, kind);
      await page.goto(editor);
      const ids = await page
        .locator("[data-editor-row]")
        .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-editor-row")!));
      expect(ids.length).toBeGreaterThan(5);
      for (const id of ids) {
        await page.goto(`${editor}?section=${id}`);
        await expect(page.locator(`[data-editor-section="${id}"]`)).toBeVisible();
        const overflow = await page.evaluate(() => {
          const main = document.getElementById("main-content")!;
          return main.scrollWidth - main.clientWidth;
        });
        expect(overflow, `section ${id}`).toBeLessThanOrEqual(0);
      }
    });
  }
});

test.describe("a page bar's back link (decision 39)", () => {
  test.use({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true });

  test("keeps its full name and never cuts its label, as the width changes", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(`${editor}?section=security`);
    const back = page.locator("[data-phone-page-bar] a").first();
    const widths = [320, 324, 328, 332, 340, 360, 375, 390, 414, 430];
    for (const width of [...widths, ...widths.toReversed()]) {
      await page.setViewportSize({ width, height: 640 });
      await expect(back).toHaveAccessibleName(/^Tillbaka till /);
      // Measured after the resize: a label shown is shown whole.
      await expect
        .poll(() =>
          back.evaluate((link) =>
            [link, ...link.querySelectorAll<HTMLElement>("*")].every(
              (element) => element.scrollWidth <= element.clientWidth + 1
            )
          )
        )
        .toBe(true);
    }
  });
});

test.describe("an editor on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keeps the section strip and every section on one page", async ({ page }) => {
    const { editor } = await assistantEditor(page);
    await page.goto(editor);
    await expect(page.locator(".astryx-tab-strip")).toBeVisible();
    await expect(page.locator("[data-editor-index]")).toBeHidden();
    await expect(page.locator("[data-phone-page-bar]")).toBeHidden();
    for (const id of ["general", "instructions", "ai"]) {
      await expect(page.locator(`[data-editor-section="${id}"]`)).toBeVisible();
    }
  });
});
