import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp";
import { audioFlow, silenceWav } from "./flows-fixture";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

// A phone: narrow and touched. It runs flows and reads their runs; it builds none.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function fitsTheWidth(page: import("@playwright/test").Page) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
}

async function axeFindsNothing(page: import("@playwright/test").Page) {
  const axe = await new AxeBuilder({
    page: page as unknown as ConstructorParameters<typeof AxeBuilder>[0]["page"]
  })
    .withTags([...WCAG_22_AA_TAGS])
    .analyze();
  expect(axe.violations).toEqual([]);
}

test(
  "a phone finds a flow under its own tab, runs it on the whole screen and reads the result first",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(180_000);
    const flow = await audioFlow(page);
    const space = flow.url.replace(/\/flows\/[^/]+$/, "");

    // Reachable: Flöden is a tab of the space, its flows are rows that say what they take and give.
    await page.goto(`${space}/overview`);
    await page
      .getByRole("navigation", { name: "Ytans innehåll" })
      .getByRole("link", { name: /^Flöden/ })
      .click();
    await expect(page).toHaveURL(/\/flows$/);
    await expect(page.getByRole("table")).toHaveCount(0);
    const rows = page.getByRole("list", { name: "Flöden" });
    await expect(rows.getByText("Indata: Ljud")).toBeVisible();
    await expect(page.getByRole("button", { name: "Nytt flöde" })).toHaveCount(0);
    await fitsTheWidth(page);
    await axeFindsNothing(page);

    // The lean flow page: what it is, its runs and one button, no editor.
    await rows.getByRole("link", { name: /E2E audio flow/ }).click();
    await expect(page).toHaveURL(new RegExp(`/flows/${flow.flowId}$`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(0);
    await expect(page.getByText("Redigera flödet på dator.")).toBeVisible();
    await fitsTheWidth(page);
    await axeFindsNothing(page);

    // The start form takes the whole screen, with nothing to drag.
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/dra hit/)).toHaveCount(0);
    const box = await dialog.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(390 - 1);
    expect(box?.height).toBeGreaterThanOrEqual(844 - 1);
    const uploaded = page.waitForResponse(
      (response) =>
        response.url().includes("/runtime-files/") && response.request().method() === "POST"
    );
    await dialog
      .locator('input[type="file"]')
      .setInputFiles({ name: "kort.wav", mimeType: "audio/wav", buffer: silenceWav(64_000) });
    expect((await uploaded).status()).toBe(201);
    // The button is in its resting colour once the upload is done (axe reads a half-faded one).
    const next = dialog.getByRole("button", { name: "Granska", exact: true });
    await expect
      .poll(() => next.evaluate((element) => getComputedStyle(element).backgroundColor))
      .toBe("rgb(26, 111, 210)");
    await fitsTheWidth(page);
    await axeFindsNothing(page);
    await dialog.getByRole("button", { name: "Granska", exact: true }).click();
    await dialog.getByRole("button", { name: "Starta körningen", exact: true }).click();

    // The run: no breadcrumbs, the result before everything else, the rest folded.
    await expect(page).toHaveURL(/\/runs\/[^/?]+$/);
    await expect(page.getByRole("heading", { level: 2, name: "Resultat" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Flöden", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Indata", exact: true })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    await fitsTheWidth(page);
    await axeFindsNothing(page);
  }
);
