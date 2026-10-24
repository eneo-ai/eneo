import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { createSpace, uniqueName } from "./helpers";

/**
 * Creates an app in a new space and starts a text run; returns the run's
 * result page. The e2e stack runs no worker, so the run stays queued: this is
 * the pending page a phone lands on after "Skicka".
 */
async function pendingResultPage(page: Page): Promise<string> {
  const space = await createSpace(page, uniqueName("App result"));
  // The API proxy accepts writes from the app's own origin only.
  const post = async (path: string, data: object) => {
    const response = await page.request.post(`/api/eneo/api/v1${path}`, {
      data,
      headers: { origin: new URL(page.url()).origin }
    });
    expect(response.ok(), await response.text()).toBe(true);
    return ((await response.json()) as { id: string }).id;
  };
  const appId = await post(`/spaces/${space.split("/").pop()}/applications/apps/`, {
    name: uniqueName("Protokoll")
  });
  const runId = await post(`/apps/${appId}/runs/`, { text: "Sammanfatta protokollet", files: [] });
  return `${space}/apps/${appId}/results/${runId}`;
}

test.describe("a pending result on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("shows its status first, a skeleton, and Ny körning docked at the bottom", async ({
    page
  }) => {
    await page.goto(await pendingResultPage(page));

    const main = page.getByRole("main");
    await expect(main.getByText("Ditt resultat genereras.")).toBeVisible();
    await expect(main.getByText("Du kan lämna sidan, resultatet sparas i Resultat.")).toBeVisible();
    // The status sits above the result, not after it.
    const status = main.getByText(/^(I kö|Pågår)$/);
    await expect(status).toBeVisible();
    const statusBox = (await status.boundingBox())!;
    const pendingBox = (await main.getByText("Ditt resultat genereras.").boundingBox())!;
    expect(statusBox.y).toBeLessThan(pendingBox.y);

    const dock = page.getByRole("group", { name: "Resultat, åtgärder" });
    const newRun = dock.getByRole("link", { name: "Ny körning" });
    await expect(newRun).toBeVisible();
    await expect(dock.getByRole("button")).toHaveCount(0);
    const dockBox = (await dock.boundingBox())!;
    expect(Math.round(dockBox.y + dockBox.height)).toBe(844);
    expect((await newRun.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    // Nothing scrolls sideways.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
  });
});

test.describe("a pending result on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keeps Ny körning in the page header", async ({ page }) => {
    await page.goto(await pendingResultPage(page));

    const dock = page.getByRole("group", { name: "Resultat, åtgärder" });
    await expect(dock).toBeVisible();
    expect(await dock.evaluate((element) => getComputedStyle(element).position)).toBe("static");
    const heading = page.getByRole("heading", { level: 1 });
    const headingBox = (await heading.boundingBox())!;
    expect((await dock.boundingBox())!.y).toBeLessThan(headingBox.y + headingBox.height + 64);
  });
});
