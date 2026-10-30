import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

// This path is authored with the manual editor; the authoring chat is never used.
test(
  "manually creates, publishes and runs a flow, then opens its history",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(120_000);
    const space = await createSpace(page, uniqueName("E2E manual flow"));
    await page.goto(`${space}/flows`);
    await page
      .getByRole("main")
      .getByRole("button", { name: "Nytt flöde", exact: true })
      .first()
      .click();
    const create = page.getByRole("dialog", { name: "Nytt flöde" });
    const flowName = uniqueName("Manuellt flöde");
    await create.getByLabel(/^Namn/i).fill(flowName);
    await create.getByRole("button", { name: "Skapa flöde", exact: true }).click();
    await expect(page).toHaveURL(/\/flows\/[^/?]+$/);
    const flowUrl = page.url();
    await page.getByRole("button", { name: "Lägg till steg", exact: true }).first().click();
    const add = page.getByRole("dialog", { name: "Lägg till steg", exact: true });
    await add.getByRole("radio", { name: "Sätt ihop text utan AI", exact: true }).check();
    await add.getByRole("textbox", { name: /^Stegnamn/ }).fill("Manuellt steg");
    await add.getByRole("button", { name: "Lägg till steget", exact: true }).click();
    await expect(add).toBeHidden();
    await page.getByRole("button", { name: /Redigera.*Manuellt steg/ }).click();
    const editorName = page.getByRole("textbox", { name: /^Stegnamn/ });
    await expect(editorName).toHaveValue("Manuellt steg");
    await page
      .getByRole("textbox", { name: /^Egen text till steget/ })
      .fill("Det manuella flödet fungerar.");
    const uploads = page.getByRole("switch", { name: /^Ta emot filer/ });
    await uploads.focus();
    await page.keyboard.press("Space");
    await expect(uploads).toBeChecked();
    const txt = page.getByRole("checkbox", { name: "TXT", exact: true });
    await txt.focus();
    await page.keyboard.press("Space");
    await expect(txt).toBeChecked();

    await page.evaluate(() => history.back());
    const leave = page.getByRole("alertdialog");
    await expect(leave).toBeVisible();
    await leave.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(page.getByRole("textbox", { name: /^Egen text till steget/ })).toHaveValue(
      "Det manuella flödet fungerar."
    );

    await page.setViewportSize({ width: 320, height: 844 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
    const axe = await new AxeBuilder({
      page: page as unknown as ConstructorParameters<typeof AxeBuilder>[0]["page"]
    })
      .withTags(WCAG_22_AA_TAGS)
      .analyze();
    expect(axe.violations).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("manual-flow-editor-mobile.png"),
      fullPage: true
    });
    await page.getByRole("button", { name: "Spara steget", exact: true }).click();
    await expect(page.getByText("Steget är sparat.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Alla steg", exact: true }).click();
    await expect(page).toHaveURL(flowUrl);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.getByRole("button", { name: "Publicera", exact: true }).click();
    await expect(page.getByRole("button", { name: "Kör flödet", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const run = page.getByRole("dialog", { name: `Kör ${flowName}` });
    await run.locator('input[type="file"]').setInputFiles({
      name: "underlag.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Testunderlag")
    });
    const runName = uniqueName("Manuell körning");
    await run.getByRole("textbox", { name: /^Namn på körningen/ }).fill(runName);
    await run.getByRole("button", { name: "Granska", exact: true }).click();
    await expect(
      run.getByRole("heading", { name: "Det här följer med i körningen" })
    ).toBeVisible();
    await run.getByRole("button", { name: "Starta körningen", exact: true }).click();
    await expect(page).toHaveURL(/\/runs\/[^/?]+$/);
    const runUrl = page.url();
    await expect(page.getByRole("heading", { name: runName, exact: true })).toBeVisible();
    await expect(
      page.getByText("Det manuella flödet fungerar.", { exact: true }).first()
    ).toBeVisible({ timeout: 60_000 });
    await page.goto(`${flowUrl}?tab=runs`);
    await expect(page.getByRole("link", { name: runName, exact: true })).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath("flow-run-history-desktop.png"),
      fullPage: true
    });
    await page.getByRole("link", { name: runName, exact: true }).click();
    await expect(page).toHaveURL(runUrl);
  }
);
