import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { apiPost, createSpace, flowsShown, uniqueName } from "./helpers";

// A phone turned sideways is wider than 768 px but under 500 px tall: it keeps the phone's
// layout (the top bar and its menu, a space's slim bar and its content tabs, an editor's index), so the
// header does not take most of the height. An iPad, upright or turned with its keyboard up, and a
// split window keep what they had.

const TURNED = [
  { name: "an iPhone 14", width: 844, height: 390 },
  { name: "an iPhone Pro Max", width: 932, height: 430 }
];

// The shell's top bar: a space's own header (tablets, desktop) is a <header> in main.
const TOP_BAR = "header:not(main *)";
// The side navigation; on a phone its twin is in the closed drawer, out of the accessibility tree.
const sideNav = (page: Page) =>
  page.getByRole("navigation", { name: /^(Huvudmeny|Main menu|Ytans meny|Space menu)$/ });

async function spaceWithAssistant(page: Page) {
  const name = uniqueName("E2E Turned");
  const space = await createSpace(page, name);
  const id = await apiPost(page, `/spaces/${space.split("/").pop()}/applications/assistants/`, {
    name: uniqueName("Bygglov")
  });
  return { name, space, editor: `${space}/assistants/${id}/edit` };
}

for (const size of TURNED) {
  test.describe(`${size.name} turned sideways`, () => {
    test.use({
      viewport: { width: size.width, height: size.height },
      hasTouch: true,
      isMobile: true
    });

    test("gets the phone's shell, space header and editor index", async ({ page }) => {
      const { name, space, editor } = await spaceWithAssistant(page);

      await page.goto(`${space}/overview`);
      await expect(
        page.getByRole("link", { name: /^(Tillbaka till|Back to) (Dina ytor|Your spaces)$/ })
      ).toBeVisible();
      await expect(page.locator(TOP_BAR)).toBeHidden();
      await expect(sideNav(page)).toBeHidden();
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      const tabs = page.getByRole("navigation", { name: /^(Ytans innehåll|Space content)$/ });
      // Översikt, Assistenter, Appar and Kunskap, and Flöden where the user has flows.
      await expect(tabs.getByRole("link")).toHaveCount((await flowsShown(page)) ? 5 : 4);
      const manage = page.getByRole("region", { name: /^(Hantera ytan|Manage space)$/ });
      await expect(manage.getByRole("link", { name: /^(Medlemmar|Members)/ })).toBeVisible();
      await expect(manage.getByRole("link", { name: /^(Inställningar|Settings)/ })).toBeVisible();

      // The space list has the shell's top bar with the menu, not the icon rail.
      await page.goto("/spaces/list");
      await expect(page.locator(TOP_BAR)).toBeVisible();
      await expect(page.getByRole("button", { name: /^(Öppna menyn|Open menu)$/ })).toBeVisible();

      await page.goto(editor);
      const index = page.getByRole("navigation", { name: /^(Avsnitt|Sections)$/ });
      const instructions = index.getByRole("link", { name: /^(Instruktioner|Instructions)/ });
      await expect(instructions).toBeVisible();
      await expect(page.locator("[data-editor-section]").first()).toBeHidden();
      await expect(page.locator("[data-space-full-bleed] > header")).toBeHidden();
      await instructions.click();
      await expect(page.locator("#assistant-prompt")).toBeVisible();
      await expect(
        page
          .locator("[data-phone-page-bar]")
          .getByRole("link", { name: /^(Tillbaka till|Back to) / })
      ).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        size.width
      );
    });
  });
}

test.describe("a docked bar on a phone turned sideways", () => {
  test.use({ viewport: { width: 844, height: 390 }, hasTouch: true, isMobile: true });

  test("gives way to a text field's keyboard, not to a switch", async ({ page }) => {
    await page.goto("/account/api-keys");
    const main = page.getByRole("main");
    const bar = page.locator("[data-docked-actions]");
    await expect(bar).toBeVisible();

    await main.getByRole("switch").first().focus();
    await expect(bar).toBeVisible();

    await main.getByRole("textbox").first().focus();
    await expect(bar).toBeHidden();
    await main.getByRole("switch").first().focus();
    await expect(bar).toBeVisible();
  });
});

test.describe("a docked bar on an upright phone", () => {
  // Android resizes the window for the keyboard (interactive-widget=resizes-content);
  // the small phone's window is then wider than tall.
  for (const viewport of [
    { width: 390, height: 460 },
    { width: 360, height: 320 }
  ]) {
    test.describe(`${viewport.width} × ${viewport.height}`, () => {
      test.use({ viewport, hasTouch: true, isMobile: true });

      test("stays above the keyboard while a text field has focus", async ({ page }) => {
        await page.goto("/account/api-keys");
        const bar = page.locator("[data-docked-actions]");
        await expect(bar).toBeVisible();
        await page.getByRole("main").getByRole("textbox").first().focus();
        await expect(bar).toBeVisible();
      });
    });
  }
});

test.describe("a phone turned while an editor's section is open", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("stays on the section with what was typed and the focus", async ({ page }) => {
    const { editor } = await spaceWithAssistant(page);
    await page.goto(`${editor}?section=instructions`);
    const prompt = page.locator("#assistant-prompt");
    await prompt.fill("Svara kort.");
    await page.setViewportSize({ width: 844, height: 390 });
    await expect(page).toHaveURL(/\?section=instructions$/);
    await expect(prompt).toBeFocused();
    await expect(prompt).toHaveValue("Svara kort.");
    await expect(page.locator("[data-phone-page-bar]").first()).toBeVisible();
  });
});

test.describe("an iPad keeps the tablet's layout", () => {
  for (const size of [
    { name: "turned with its keyboard up", width: 1180, height: 470 },
    { name: "upright", width: 820, height: 1180 }
  ]) {
    test.describe(size.name, () => {
      test.use({ viewport: { width: size.width, height: size.height }, hasTouch: true });

      test("shows the side navigation and the space's header with all its tabs", async ({
        page
      }) => {
        const { space } = await spaceWithAssistant(page);
        await page.goto(`${space}/overview`);
        await expect(sideNav(page)).toBeVisible();
        await expect(page.locator("[data-phone-page-bar]")).toBeHidden();
        await expect(
          page.getByRole("region", { name: /^(Hantera ytan|Manage space)$/ })
        ).toHaveCount(0);
      });
    });
  }
});

test.describe("an iPad split in half", () => {
  test.use({ viewport: { width: 590, height: 820 }, hasTouch: true, isMobile: true });

  test("keeps the phone's layout", async ({ page }) => {
    const { space } = await spaceWithAssistant(page);
    await page.goto(`${space}/overview`);
    await expect(page.locator("[data-phone-page-bar]")).toBeVisible();
    await expect(sideNav(page)).toBeHidden();
  });
});
