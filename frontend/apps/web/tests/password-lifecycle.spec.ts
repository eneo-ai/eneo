import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { backendFetch, expectOk, uniqueName } from "./helpers";

/** The tests below toggle the tenant rule; each starts from, and leaves, the default. */
async function setOneTimeRule(page: Page, request: APIRequestContext, enabled: boolean) {
  const response = await backendFetch(page, request, "/api/v1/admin/password-policy", {
    method: "PATCH",
    data: { require_change_after_admin_set: enabled }
  });
  await expectOk(response, "setting the one-time password rule");
}

// A password an administrator hands out is one-time: the account signs in with
// it, is sent to /password-change, chooses its own, signs in again and lands
// where it was going. Runs in the admin session for setup, then in a fresh
// context for the new account. The UI speaks Swedish, the app's base locale.
test("an admin-set password must be replaced at the first sign-in", async ({
  page,
  request,
  browser
}) => {
  await setOneTimeRule(page, request, true);
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Lösenordspolicy" })).toBeVisible();

  const email = `${uniqueName("e2e-onetime").replace(/\s+/g, "-").toLowerCase()}@example.com`;
  const oneTimePassword = "OneTimePassword1!";
  const chosenPassword = "ChosenByTheUser2!";

  const created = await backendFetch(page, request, "/api/v1/admin/users/", {
    method: "POST",
    data: { email, username: email.split("@")[0], password: oneTimePassword }
  });
  await expectOk(created, "creating the one-time password user");

  // The admin list marks the account until it has chosen its own password.
  await page.goto(`/admin/users?search=${encodeURIComponent(email)}`);
  const row = page.getByRole("row", { name: new RegExp(email) });
  await expect(row.getByText("Engångslösenord", { exact: true })).toBeVisible();

  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const newUser = await context.newPage();
  try {
    await newUser.goto("/spaces/personal/chat");
    await newUser.locator('input[name="email"]').fill(email);
    await newUser.locator('input[name="password"]').fill(oneTimePassword);
    await newUser.locator('button[type="submit"]').click();

    await expect(newUser).toHaveURL(/\/password-change/);
    await expect(newUser.getByRole("heading", { name: "Välj ett nytt lösenord" })).toBeVisible();
    await expect(newUser.getByText(/sattes av en administratör/)).toBeVisible();

    // The app shell stays closed to this session until the password is replaced.
    await newUser.goto("/spaces/personal/chat");
    await expect(newUser).toHaveURL(/\/password-change/);

    await newUser.getByLabel("Nuvarande lösenord").fill(oneTimePassword);
    await newUser.getByLabel("Nytt lösenord", { exact: true }).fill(chosenPassword);
    await newUser.getByLabel("Bekräfta nytt lösenord").fill(chosenPassword);
    await newUser.getByRole("button", { name: "Byt lösenord" }).click();

    await expect(newUser).toHaveURL(/\/login\?message=password_changed/);
    await newUser.locator('input[name="email"]').fill(email);
    await newUser.locator('input[name="password"]').fill(chosenPassword);
    await newUser.locator('button[type="submit"]').click();
    await newUser.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
    await expect(newUser).not.toHaveURL(/\/password-change/);

    // The one-time password is gone for good.
    await newUser.context().clearCookies();
    await newUser.goto("/login");
    await newUser.locator('input[name="email"]').fill(email);
    await newUser.locator('input[name="password"]').fill(oneTimePassword);
    await newUser.locator('button[type="submit"]').click();
    await expect(newUser.getByRole("alert")).toBeVisible();
    await expect(newUser).toHaveURL(/\/login/);
  } finally {
    await context.close();
  }

  await page.goto(`/admin/users?search=${encodeURIComponent(email)}`);
  const settled = page.getByRole("row", { name: new RegExp(email) });
  await expect(settled).toBeVisible();
  await expect(settled.getByText("Engångslösenord", { exact: true })).toHaveCount(0);
});

test("an administrator can turn the one-time rule off and on", async ({ page, request }) => {
  await setOneTimeRule(page, request, true);
  await page.goto("/admin/users");
  const panel = page.locator('[data-tour="admin-password-policy"]');
  const ruleName = "Lösenord satta av administratör är engångslösenord";
  await expect(panel.getByRole("switch", { name: ruleName })).toBeChecked();
  const save = panel.getByRole("button", { name: "Spara" });
  await expect(save).toBeDisabled();

  await panel.getByRole("switch", { name: ruleName }).click();
  await save.click();
  await expect(panel.getByRole("status")).toContainText("Lösenordspolicyn är sparad");
  await page.reload();
  await expect(panel.getByRole("switch", { name: ruleName })).not.toBeChecked();

  await panel.getByRole("switch", { name: ruleName }).click();
  await panel.getByRole("button", { name: "Spara" }).click();
  await expect(panel.getByRole("status")).toContainText("Lösenordspolicyn är sparad");
  await setOneTimeRule(page, request, true);
});
