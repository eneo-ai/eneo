import { expect, test } from "./csp";
import { collectAssetFailures, productionAsset } from "./helpers";

test.describe("production chunk recovery", { tag: "@vite" }, () => {
  test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served production Vite build.");

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
});
