import { expect, test } from "./csp";

// The CSP fixture itself (tests/csp.ts): specs that import `test` from it
// fail on any Content-Security-Policy violation.

test("records what the Content-Security-Policy blocks", async ({ page, cspViolations }) => {
  await page.goto("/spaces/list");
  await expect(page.locator("main#main-content")).toBeVisible();
  expect(cspViolations, "violations while the page loaded").toEqual([]);

  // img-src allows only the app's own origin, blob: and data:, in production
  // and on the dev server alike.
  await page.evaluate(() => {
    const image = document.createElement("img");
    image.src = "https://csp-probe.invalid/pixel.png";
    document.body.append(image);
  });

  await expect.poll(() => cspViolations.length).toBe(1);
  // Browsers may report a cross-origin resource by its origin only.
  expect(cspViolations[0]).toContain("img-src blocked https://csp-probe.invalid");
  // Provoked on purpose: nothing left for the fixture to fail on.
  cspViolations.length = 0;
});
