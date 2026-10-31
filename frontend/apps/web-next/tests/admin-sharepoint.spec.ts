import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import m from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";

const STATE_KEY = "sharepoint_service_account_oauth";
const reply = (route: Route, json: unknown, status = 200) =>
  route.fulfill({ status, headers: sessionResponseHeaders(route), json });
async function scan(page: Page) {
  type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
  const result = await new AxeBuilder({ page: page as unknown as AxePage })
    .withTags(WCAG_22_AA_TAGS)
    .analyze();
  expect(
    result.violations.map((item) => ({ id: item.id, nodes: item.nodes.map((node) => node.target) }))
  ).toEqual([]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  ).toBeLessThanOrEqual(0);
}
const app = {
  id: "fixture-app",
  tenant_id: "tenant",
  client_id: "fixture-client",
  client_secret_masked: "****1234",
  tenant_domain: "example.onmicrosoft.com",
  is_active: true,
  auth_method: "service_account",
  service_account_email: "service@example.se",
  auth_status: "ok",
  certificate_path: null,
  created_by: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-10-31T00:00:00Z"
};
// Real FastAPI cookie session, shell and CSP; Microsoft/Graph replies and the
// external sign-in page below are fixtures, without a configured Microsoft tenant.
test(
  "manages saved SharePoint credentials and subscriptions, then shows the service-account return",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    let failedRead = true;
    let current = { ...app };
    let subscriptionReads = 0;
    let recreates = 0;
    const testBodies: (string | null)[] = [];
    const callbacks: unknown[] = [];
    await page.route(/\/api\/v1\/admin\/sharepoint\/app$/, (route) =>
      failedRead ? reply(route, { message: "Fixture denied" }, 403) : reply(route, current)
    );
    await page.route(/\/api\/v1\/admin\/sharepoint\/subscriptions$/, (route) => {
      subscriptionReads += 1;
      return reply(route, [
        {
          id: "sub-1",
          user_integration_id: "connection",
          subscription_id: "graph-1",
          owner_type: "organization",
          owner_email: null,
          site_id: "site-fixture",
          drive_id: "drive-fixture",
          expires_at: "2026-11-05T00:00:00Z",
          expires_in_hours: 120,
          created_at: "2026-10-01T08:00:00Z",
          is_expired: false,
          consecutive_renewal_failures: 1,
          last_renewal_failed_at: "2026-10-30T08:00:00Z",
          last_renewal_error: "Fixture webhook refused",
          last_webhook_received_at: null
        }
      ]);
    });
    await page.route(/\/api\/v1\/admin\/sharepoint\/subscriptions\/recreate-all$/, (route) => {
      recreates += 1;
      return reply(route, {
        total_subscriptions: 3,
        recreated: 2,
        failed: 1,
        errors: ["Fixture webhook refused"]
      });
    });
    await page.route(/\/api\/v1\/admin\/sharepoint\/app\/test$/, (route) => {
      testBodies.push(route.request().postData());
      current = { ...current, auth_status: "error" };
      return reply(route, { success: false, error_message: "invalid_client: AADSTS7000215" });
    });
    await page.route(/\/api\/v1\/admin\/sharepoint\/service-account\/auth\/reauth$/, (route) =>
      reply(route, {
        auth_url: "https://login.microsoftonline.com/native-fixture",
        state: "native-state"
      })
    );
    await page.route("https://login.microsoftonline.com/native-fixture", (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<html><body>Microsoft sign-in fixture</body></html>"
      })
    );
    await page.route(/\/api\/v1\/admin\/sharepoint\/service-account\/auth\/callback$/, (route) => {
      callbacks.push(route.request().postDataJSON());
      current = { ...app };
      return reply(route, current);
    });
    await page.goto("/admin/integrations");
    const section = page.getByRole("region", { name: m.sharepoint_health_row_title });
    await expect(section.getByRole("button", { name: /Försök igen/ })).toBeVisible();
    await expect(
      section.getByRole("button", { name: m.configure_sharepoint_app, exact: true })
    ).toHaveCount(0);
    failedRead = false;
    await section.getByRole("button", { name: /Försök igen/ }).click();
    await expect(section.getByText(m.sharepoint_auth_status_ok, { exact: true })).toBeVisible();
    await section.getByRole("button", { name: m.sharepoint_health_watch_show }).click();
    const table = section.getByRole("table", { name: m.sharepoint_subscriptions_title });
    await expect(table.getByText(/drive-fixture/)).toBeVisible();
    await expect(table.getByText("5d kvar", { exact: true })).toBeVisible();
    await expect(table.locator('time[datetime="2026-10-30T08:00:00.000Z"]')).toBeVisible();
    await section
      .getByRole("button", { name: m.sharepoint_subscriptions_recreate_all, exact: true })
      .click();
    await expect.poll(() => recreates).toBe(0);
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: m.confirm, exact: true })
      .click();
    await expect(
      page
        .locator("[data-sonner-toast]")
        .getByText("2 återskapade, 1 misslyckades. Fel: Fixture webhook refused", { exact: true })
    ).toBeVisible();
    await expect.poll(() => subscriptionReads).toBeGreaterThan(1);
    expect(recreates).toBe(1);
    await section.getByRole("button", { name: m.update_configuration, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: m.configure_sharepoint_app_title });
    await expect(dialog.getByText(m.auth_method, { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: m.sharepoint_health_test_title, exact: true }).click();
    await expect(
      dialog.locator("p").filter({ hasText: m.sharepoint_auth_guidance_invalid_client })
    ).toBeVisible();
    expect(testBodies).toEqual([null]);
    await page.setViewportSize({ width: 390, height: 844 });
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await scan(page);
      await page.screenshot({
        path: testInfo.outputPath(`admin-sharepoint-config-${colorScheme}.png`),
        fullPage: true
      });
    }
    await dialog
      .getByRole("button", { name: m.sharepoint_reauth_with_microsoft, exact: true })
      .click();
    await expect(page).toHaveURL("https://login.microsoftonline.com/native-fixture");
    const origin = testInfo.project.use.baseURL!;
    await page.goto(`${origin}/integrations/callback/token/?code=native-code&state=native-state`);
    await expect(
      page.getByRole("heading", { name: m.service_account_configured, exact: true })
    ).toBeVisible();
    await expect(page.getByText("service@example.se", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/integrations\/callback\/token\/?$/);
    expect(callbacks).toEqual([{ auth_code: "native-code", state: "native-state" }]);
    expect(await page.evaluate((key) => sessionStorage.getItem(key), STATE_KEY)).toBeNull();
    await scan(page);
    await page.screenshot({
      path: testInfo.outputPath("admin-sharepoint-callback-success.png"),
      fullPage: true
    });
    await page.getByRole("link", { name: m.back_to_integrations, exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/integrations\/?$/);
  }
);

for (const [name, query, text] of [
  [
    "refusal",
    "error=access_denied&error_description=%3Cscript%3Erefused%3C%2Fscript%3E&code=ignored&state=expected",
    "<script>refused</script>"
  ],
  ["mismatch", "code=ignored&state=wrong", m.sharepoint_callback_state_invalid]
]) {
  test(
    `service-account callback ${name} stays safe and offers a local return`,
    { tag: "@vite" },
    async ({ page }) => {
      await page.addInitScript(
        (key) => sessionStorage.setItem(key, JSON.stringify({ state: "expected" })),
        STATE_KEY
      );
      let posts = 0;
      await page.route(
        /\/api\/v1\/admin\/sharepoint\/service-account\/auth\/callback$/,
        (route) => {
          posts += 1;
          return reply(route, app);
        }
      );
      await page.goto(`/integrations/callback/token/?${query}`);
      await expect(
        page.getByRole("heading", { name: m.authentication_failed, exact: true })
      ).toBeVisible();
      await expect(page.locator("main p").filter({ hasText: text })).toBeVisible();
      await expect(page.locator("main script")).toHaveCount(0);
      await expect(page.getByRole("link", { name: m.back_to_integrations })).toHaveAttribute(
        "href",
        "/admin/integrations"
      );
      await expect(page).toHaveURL(/\/integrations\/callback\/token\/?$/);
      expect(posts).toBe(0);
      await scan(page);
    }
  );
}
