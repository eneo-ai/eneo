import { expect, test } from "./csp";
import { collectAssetFailures, productionAsset } from "./helpers";

test.describe("production chunk recovery", { tag: "@vite" }, () => {
  test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served production Vite build.");

  test("shares one reload between a missing feature chunk and a later missing route", async ({
    page
  }) => {
    const missing = new Set([
      productionAsset("src/features/admin/insights/usage-area-chart.tsx"),
      productionAsset("src/routes/_app/account/index.tsx?tsr-split=component")
    ]);
    let documents = 0;
    const failures = collectAssetFailures(page, missing);
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++;
    });
    await page.route(
      (url) => missing.has(url.pathname),
      (route) =>
        route.fulfill({ status: 404, contentType: "text/plain", body: "Removed deployment asset" })
    );

    await page.goto("/admin/insights");
    await expect(
      page.getByRole("heading", { name: /något gick fel|something went wrong/i })
    ).toBeVisible();
    expect(documents, "initial navigation and one recovery reload").toBe(2);

    await page.goto("/account");
    await expect(
      page.getByRole("heading", { name: /något gick fel|something went wrong/i })
    ).toBeVisible();
    expect(documents, "a different missing chunk must not get a new automatic reload").toBe(3);
    expect(failures, "unexpected production asset failures").toEqual([]);
  });
});
