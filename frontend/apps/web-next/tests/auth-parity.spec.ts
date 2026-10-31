import type { Page } from "@playwright/test";
import { expect, test } from "./csp";

test.use({ storageState: { cookies: [], origins: [] } });

async function federationChoices(page: Page, single = false) {
  await page.route("**/api/v1/auth/federation-status", (route) =>
    route.fulfill({
      json: {
        has_global_oidc_config: false,
        has_single_tenant_federation: false,
        has_multi_tenant_federation: true,
        tenant_count: single ? 1 : 2
      }
    })
  );
  const tenants = [
    { slug: "north", name: "Northern municipality", display_name: "Norra kommunen" },
    { slug: "south", name: "Southern municipality", display_name: "Södra kommunen" }
  ];
  await page.route("**/api/v1/auth/tenants", (route) =>
    route.fulfill({ json: { tenants: single ? tenants.slice(0, 1) : tenants } })
  );
}

test("organisation search and login reference copy remain usable with a federation catalog", async ({
  page,
  context
}) => {
  await federationChoices(page);
  await page.goto("/login?tenant=");
  const search = page.getByRole("textbox", { name: "Sök organisationer" });
  await search.fill("south");
  await expect(page.getByRole("link", { name: "Södra kommunen" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Norra kommunen" })).toHaveCount(0);
  await expect(page.getByRole("status", { name: "Sök organisationer" })).toHaveText(
    "1 organisation hittades"
  );
  await search.fill("missing");
  await expect(page.getByText("Inga organisationer hittades", { exact: true })).toBeVisible();
  await search.fill("");
  await expect(page.getByRole("link", { name: "Norra kommunen" })).toBeVisible();

  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/login/failed?detailCode=no_code_received&correlation=browser-reference");
  await expect(page.getByText("browser-reference", { exact: true })).toBeVisible();
  const copy = page.getByRole("button", { name: "Kopiera korrelations-ID till urklipp" });
  await copy.focus();
  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe("browser-reference");
});

test("switch organisation clears remembered choices and keeps the sole choice explicit", async ({
  page
}) => {
  await federationChoices(page, true);
  await page.goto("/login?tenant=");
  await expect(page.getByRole("link", { name: "Norra kommunen" })).toBeVisible();
  await page.evaluate(() => {
    sessionStorage.setItem("eneo-last-tenant-slug", "north");
    localStorage.setItem("eneo:last-tenant", "north");
  });
  const signOut = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/auth/session/logout/") &&
      response.request().method() === "POST"
  );
  await page.goto("/login/switch-organisation");
  expect((await signOut).ok()).toBe(true);
  await expect(page).toHaveURL(/\/login\?tenant=$/);
  await expect(page.getByRole("link", { name: "Norra kommunen" })).toBeVisible();
  expect(
    await page.evaluate(() => [
      sessionStorage.getItem("eneo-last-tenant-slug"),
      localStorage.getItem("eneo:last-tenant")
    ])
  ).toEqual([null, null]);
});
