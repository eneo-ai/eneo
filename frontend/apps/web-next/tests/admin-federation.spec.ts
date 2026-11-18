import type { FederationView } from "../src/features/admin/federation/federation";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";

// The settings are a UI fixture: this never contacts an IdP or stores credentials.
const view: FederationView = {
  configured: true,
  provider: "Example IdP",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "e2e-client",
  client_secret_set: true,
  encryption_status: "encrypted",
  allowed_domains: ["example.org"],
  redirect_uris: ["https://eneo.example/login/callback"],
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "e2e-revision"
};

// jsdom does not make the page behind a modal inert, so focus after stacked dialogs needs a browser.
for (const stay of ["Avbryt", "Escape"] as const) {
  test(`a save that fails while the admin decides whether to leave returns focus to Save (${stay})`, async ({
    page
  }) => {
    let failSave = () => {};
    const saveHeld = new Promise<void>((resolve) => (failSave = resolve));
    await page.route("**/api/v1/admin/federation", async (route) => {
      if (route.request().method() !== "PATCH") {
        return route.fulfill({ headers: sessionResponseHeaders(route), json: view });
      }
      await saveHeld;
      return route.fulfill({
        status: 500,
        headers: sessionResponseHeaders(route),
        json: { message: "boom" }
      });
    });

    // Arrive in the app, so Back stays inside it.
    await page.goto("/admin/settings");
    await page.getByRole("link", { name: "Inloggning (SSO)", exact: true }).click();
    await page.getByRole("textbox", { name: /^Klient-ID\b/ }).fill("next-client");
    await page.getByRole("button", { name: "Spara ändringar" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Spara och använd" }).click();

    await page.evaluate(() => window.history.back());
    await expect(page.getByRole("alertdialog", { name: "Sparningen pågår" })).toBeVisible();
    failSave();
    // The save failed: the edits are unsaved again, and the same dialog now says so.
    const leave = page.getByRole("alertdialog", { name: "Lämna sidan?" });
    await expect(leave).toBeVisible();
    await expect(page.getByRole("alertdialog", { name: /Ändra inloggningen/ })).toBeHidden();
    if (stay === "Escape") await page.keyboard.press("Escape");
    else await leave.getByRole("button", { name: "Avbryt" }).click();

    await expect(leave).toBeHidden();
    await expect(page).toHaveURL(/\/admin\/federation$/);
    await expect(page.getByRole("textbox", { name: /^Klient-ID\b/ })).toHaveValue("next-client");
    await expect(page.getByRole("button", { name: "Spara ändringar" })).toBeFocused();
  });
}
