import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp";
import { apiRequest } from "./helpers";
import { audioFlow, silenceWav } from "./flows-fixture";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

// A phone: narrow and touched. It runs flows and reads their runs; it builds none.
test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
  // A recording needs a microphone: Chromium offers a fake one.
  permissions: ["microphone"],
  launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] }
});

async function fitsTheWidth(page: import("@playwright/test").Page) {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
}

/**
 * Waits until a control has stopped fading in, itself and every element around it: axe reads a
 * half-faded colour as low contrast. Three equal reads in a row, so a transition that has not
 * begun yet is not taken for one that has ended.
 */
async function resting(locator: import("@playwright/test").Locator) {
  let last = "";
  let equal = 0;
  await expect
    .poll(
      async () => {
        const now = await locator.evaluate((element) => {
          const style = getComputedStyle(element);
          let opacity = 1;
          for (let node: Element | null = element; node; node = node.parentElement) {
            opacity *= Number(getComputedStyle(node).opacity);
          }
          return `${style.backgroundColor}|${style.color}|${opacity.toFixed(3)}`;
        });
        equal = now === last ? equal + 1 : 0;
        last = now;
        return equal >= 2;
      },
      { intervals: [150] }
    )
    .toBe(true);
}

/** The control is on the screen (a footer pushed below a long form is not): what a thumb reaches. */
async function onScreen(
  page: import("@playwright/test").Page,
  locator: import("@playwright/test").Locator
) {
  await expect
    .poll(async () => {
      const box = await locator.boundingBox();
      const height = await page.evaluate(() => innerHeight);
      return box !== null && box.y >= 0 && box.y + box.height <= height + 1;
    })
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

    // Reachable: Flöden is a tab of the space, its flows are rows under their state that say what
    // they take and give.
    await page.goto(`${space}/overview`);
    await page
      .getByRole("navigation", { name: "Ytans innehåll" })
      .getByRole("link", { name: /^Flöden/ })
      .click();
    await expect(page).toHaveURL(/\/flows$/);
    await expect(page.getByRole("table")).toHaveCount(0);
    const rows = page.getByRole("region", { name: "Publicerad", exact: true }).getByRole("list");
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
    const next = dialog.getByRole("button", { name: "Nästa", exact: true });
    await expect
      .poll(() => next.evaluate((element) => getComputedStyle(element).backgroundColor))
      .toBe("rgb(26, 111, 210)");
    await fitsTheWidth(page);
    await axeFindsNothing(page);
    await dialog.getByRole("button", { name: "Nästa", exact: true }).click();
    await dialog.getByRole("button", { name: "Starta körningen", exact: true }).click();

    // The run: no breadcrumbs, the result before everything else, the rest folded.
    await expect(page).toHaveURL(/\/runs\/[^/?]+$/);
    await expect(page.getByRole("heading", { level: 2, name: "Resultat" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Flöden", exact: true })).toHaveCount(0);
    for (const fold of ["Det du fyllde i", "Bevisunderlag"]) {
      await expect(page.getByRole("button", { name: fold, exact: true })).toHaveAttribute(
        "aria-expanded",
        "false"
      );
    }
    await fitsTheWidth(page);
    await axeFindsNothing(page);

    // The stack allows only a few active runs at a time: leave none of this test's behind.
    const runId = new URL(page.url()).pathname.split("/").at(-1)!;
    await apiRequest(page, `/flows/${flow.flowId}/runs/${runId}/cancel/`, { method: "POST" });
  }
);

test(
  "a phone records first, with controls as wide as the screen, and a turn sideways does not end a recording",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(120_000);
    const flow = await audioFlow(page);
    await page.goto(flow.url);
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const y = async (locator: import("@playwright/test").Locator) =>
      (await locator.boundingBox())!.y;

    // The microphone is the way in a phone has: recording comes first, the start button is as wide
    // as the screen and a thumb tall, the file is a field under it, and the run's name is last.
    const start = dialog.getByRole("button", { name: "Spela in", exact: true });
    const startBox = (await start.boundingBox())!;
    expect(startBox.width).toBeGreaterThan(300);
    expect(startBox.height).toBeGreaterThanOrEqual(44);
    expect(await y(start)).toBeLessThan(await y(dialog.getByText("Välj filer", { exact: true })));
    expect(await y(dialog.getByText("Välj filer", { exact: true }))).toBeLessThan(
      await y(dialog.getByLabel(/^Namn i listan över körningar/))
    );
    await fitsTheWidth(page);
    await resting(start);
    await axeFindsNothing(page);

    await start.click();
    const pause = dialog.getByRole("button", { name: "Pausa", exact: true });
    const stop = dialog.getByRole("button", { name: "Stoppa", exact: true });
    await expect(stop).toBeVisible();
    // The clock is read first; each control is as wide as the screen.
    expect(await y(dialog.getByText("Spelar in", { exact: true }))).toBeLessThan(await y(pause));
    for (const control of [pause, stop]) {
      const box = (await control.boundingBox())!;
      expect(box.width).toBeGreaterThan(300);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    await fitsTheWidth(page);
    await resting(pause);
    await resting(stop);
    await axeFindsNothing(page);

    // Turned sideways (past 768 px) and back, the recording goes on, and the form scrolls above its
    // footer in both.
    const review = dialog.getByRole("button", { name: "Nästa", exact: true });
    await onScreen(page, review);
    await page.setViewportSize({ width: 844, height: 390 });
    await expect(stop).toBeVisible();
    await expect(start).toHaveCount(0);
    await onScreen(page, review);
    // Sideways it is still a phone: the recording is still first and the form still the whole screen.
    expect(await y(stop)).toBeLessThan(await y(dialog.getByText("Välj filer", { exact: true })));
    const sideways = (await dialog.boundingBox())!;
    expect(sideways.width).toBeGreaterThanOrEqual(844 - 1);
    expect(sideways.height).toBeGreaterThanOrEqual(390 - 1);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(stop).toBeVisible();
    await expect(start).toHaveCount(0);

    await stop.click();
    await expect(dialog.getByText(/Uppladdad/)).toBeVisible({ timeout: 30_000 });
    // A form with a recording in it is taller than the screen, and still ends in its buttons.
    await onScreen(page, review);
    // Recording again goes on with the same recording.
    await expect(dialog.getByRole("button", { name: "Spela in mer", exact: true })).toBeVisible();
  }
);

test.describe("on the smallest phone", () => {
  test.use({ viewport: { width: 320, height: 568 } });

  test("the start form scrolls above its buttons", { tag: "@vite" }, async ({ page }) => {
    test.setTimeout(120_000);
    const flow = await audioFlow(page);
    await page.goto(flow.url);
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Spela in", exact: true })).toBeVisible();
    await onScreen(page, dialog.getByRole("button", { name: "Nästa", exact: true }));
    await onScreen(page, dialog.getByRole("button", { name: "Avbryt", exact: true }));
    await fitsTheWidth(page);
  });
});
