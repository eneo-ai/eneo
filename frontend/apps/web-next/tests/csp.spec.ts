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

test("Astryx layers get their slide rules past the CSP", async ({ page, cspViolations }) => {
  // The chat mounts Astryx layers (tooltips, popovers) on load; the first one
  // installs the `@position-try` rules that let a layer slide or flip at the
  // viewport edge (frontend/patches/@astryxdesign%2Fcore@0.7.3.patch).
  await page.goto("/spaces/personal/chat");
  await expect
    .poll(() =>
      page.evaluate(() => {
        const rules = document.getElementById("astryx-layer-slide-rules");
        const sheet = [...document.styleSheets].find((sheet) => sheet.ownerNode === rules);
        return sheet?.cssRules.length ?? 0;
      })
    )
    .toBeGreaterThan(0);
  expect(cspViolations, "violations while the chat loaded").toEqual([]);
});

test("a legacy Select opens without a <style> the CSP blocks", async ({ page, cspViolations }) => {
  // An open Radix Select injects two <style> elements, its viewport's and the
  // page's scroll lock; both need the request nonce (src/components/providers/nonce.tsx).
  await page.goto("/account");
  await page.getByRole("combobox", { name: /^(Språk|Language)$/ }).click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toBeHidden();
  expect(cspViolations, "violations while the Select was open").toEqual([]);
});
