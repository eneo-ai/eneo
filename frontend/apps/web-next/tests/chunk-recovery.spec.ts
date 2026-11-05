import { expect, test } from "./csp";
import { chatComposer, collectAssetFailures, productionAsset } from "./helpers";

test.describe("production chunk recovery", () => {
  test("shares one reload between a missing feature chunk and a later missing route", async ({
    page
  }) => {
    const featureChunk = productionAsset("src/features/admin/insights/usage-area-chart.tsx");
    const routeChunk = productionAsset("src/routes/_app/account/index.tsx?tsr-split=component");
    const missing = new Set([featureChunk, routeChunk]);
    const missingRequests = new Map<string, number>();
    let documents = 0;
    const failures = collectAssetFailures(page, missing);
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++;
    });
    await page.route(
      (url) => missing.has(url.pathname),
      async (route) => {
        const path = new URL(route.request().url()).pathname;
        missingRequests.set(path, (missingRequests.get(path) ?? 0) + 1);
        await route.fulfill({
          status: 404,
          contentType: "text/plain",
          body: "Removed deployment asset"
        });
      }
    );

    await page.goto("/admin/insights");
    // Both app bootstraps must reach the lazy import before checking the error UI.
    await expect.poll(() => missingRequests.get(featureChunk), { timeout: 15_000 }).toBe(2);
    await expect(
      page.getByRole("heading", { name: /något gick fel|something went wrong/i })
    ).toBeVisible();
    expect(documents, "initial navigation and one recovery reload").toBe(2);

    await page.goto("/account");
    await expect.poll(() => missingRequests.get(routeChunk), { timeout: 15_000 }).toBe(1);
    await expect(
      page.getByRole("heading", { name: /något gick fel|something went wrong/i })
    ).toBeVisible();
    expect(documents, "a different missing chunk must not get a new automatic reload").toBe(3);
    expect(failures, "unexpected production asset failures").toEqual([]);
  });

  test("offline, a failed import keeps the page, and the link opens once back online", async ({
    page,
    context
  }) => {
    let documents = 0;
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++;
    });
    await page.goto("/spaces/personal/chat");
    await expect(chatComposer(page)).toBeVisible();

    await context.setOffline(true);
    const banner = page
      .getByRole("main")
      .getByText(/^(Du är offline|You're offline)$/)
      .filter({ visible: true });
    await expect(banner).toHaveCount(1);
    // Focus is intent: the router preloads the link's route, whose chunk is
    // out of reach. A reload would only show the browser's offline page.
    const failedImport = page.waitForEvent("requestfailed", (request) =>
      new URL(request.url()).pathname.startsWith("/assets/")
    );
    const spaces = page
      .getByRole("navigation", { name: /^(Huvudområden|Main areas)$/ })
      .getByRole("link", { name: /^(Delat|Spaces)$/ });
    await spaces.focus();
    await failedImport;
    await chatComposer(page).fill("Vilken gräns gäller?");
    await expect(chatComposer(page)).toHaveValue("Vilken gräns gäller?");
    await expect(banner).toHaveCount(1);
    expect(documents, "the chunk was out of reach, not removed: no reload").toBe(1);

    // Chromium keeps the failed import for the document, so the reload the
    // offline failure left unspent is what opens the page.
    await context.setOffline(false);
    await expect(banner).toHaveCount(0);
    await spaces.click();
    const confirmation = page.getByRole("alertdialog", { name: "Lämna chatten?", exact: true });
    await confirmation.getByRole("button", { name: "Lämna chatten", exact: true }).click();
    await expect(page).toHaveURL(/\/spaces\/list$/);
    await expect(
      page.getByRole("heading", { level: 1, name: /^(Dina ytor|Your spaces)$/ })
    ).toBeVisible();
  });
});
