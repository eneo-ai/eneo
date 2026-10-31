import { expect, test } from "./csp";
import { audioFlow, silenceWav } from "./flows-fixture";

test.skip(!process.env.E2E_BASE_URL, "needs a stack");
const OUT = "/Users/ccimen/.tmp/claude-501/-Users-ccimen-dev-eneoreactmobile/fac73bc0-86d3-458a-8087-6d4c9efc87f7/scratchpad/design/flows-live/";
for (const [w, h] of [[390, 844], [320, 568]] as const) {
  test(`shots ${w}`, async ({ browser }) => {
    test.setTimeout(150_000);
    const context = await browser.newContext({ storageState: "playwright/.auth/user.json", baseURL: process.env.E2E_BASE_URL, viewport: { width: w, height: h }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const flow = await audioFlow(page);
    const space = flow.url.replace(/\/flows\/[^/]+$/, "");
    await page.goto(`${space}/flows`); await page.waitForTimeout(1200);
    await page.screenshot({ path: OUT + `list-${w}.png` });
    await page.goto(flow.url); await page.waitForTimeout(1500);
    await page.screenshot({ path: OUT + `flow-${w}.png` });
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.locator('input[type="file"]').setInputFiles({ name: "kort.wav", mimeType: "audio/wav", buffer: silenceWav(64_000) });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: OUT + `start-${w}.png` });
    await dialog.getByRole("button", { name: "Granska", exact: true }).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: OUT + `review-${w}.png` });
    await dialog.getByRole("button", { name: "Starta körningen", exact: true }).click();
    await expect(page).toHaveURL(/\/runs\/[^/?]+$/);
    await page.waitForTimeout(6000);
    await page.screenshot({ path: OUT + `run-${w}.png` });
    await context.close();
  });
}
