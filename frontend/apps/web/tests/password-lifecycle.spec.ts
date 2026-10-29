import { expect, test } from "@playwright/test";
import { uniqueName } from "./helpers";

// An administrator never types a password for someone else: Eneo generates
// one, shows it once, and it is one-time. The account signs in with it, is
// sent to /password-change, chooses its own, signs in again and lands where it
// was going. Runs in the admin session for setup, then in a fresh context for
// the new account. The UI speaks Swedish, the app's base locale.
test("a generated admin-set password must be replaced at the first sign-in", async ({
  page,
  browser
}) => {
  test.setTimeout(60_000);

  const email = `${uniqueName("e2e-onetime").replace(/\s+/g, "-").toLowerCase()}@example.com`;
  const chosenPassword = "ChosenByTheUser2!";

  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Lösenordspolicy" })).toBeVisible();
  // The button is server-rendered, and hydration ends after the load event that
  // goto() waits for: a click before it attaches the handler is lost.
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Skapa användare" }).click();
  const editor = page.getByRole("dialog");
  await editor.getByLabel("Användarnamn").fill(email.split("@")[0]);
  await editor.getByLabel("E-post").fill(email);
  await expect(editor.locator('input[type="password"]')).toHaveCount(0);
  await editor.getByRole("button", { name: "Skapa användare" }).click();

  // Shown once, after the account exists, for the administrator to hand over.
  await expect(editor.getByText("Kontot har skapats")).toBeVisible();
  await expect(editor.getByText(`Lämna lösenordet till ${email}.`)).toBeVisible();
  const oneTimePassword = await editor.getByLabel("Lösenord", { exact: true }).inputValue();
  expect(oneTimePassword.length).toBeGreaterThanOrEqual(12);
  await editor.getByRole("button", { name: "Klar" }).click();
  await expect(editor).toHaveCount(0);

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

    await expect(newUser).toHaveURL(/\/password-change/, { timeout: 15_000 });
    await expect(newUser.getByRole("heading", { name: "Välj ett nytt lösenord" })).toBeVisible();
    await expect(newUser.getByText(/sattes av en administratör/)).toBeVisible();

    // The app shell stays closed to this session until the password is replaced.
    await newUser.goto("/spaces/personal/chat");
    await expect(newUser).toHaveURL(/\/password-change/);

    await newUser.getByLabel("Nuvarande lösenord").fill(oneTimePassword);
    await newUser.getByLabel("Nytt lösenord", { exact: true }).fill(chosenPassword);
    await newUser.getByLabel("Bekräfta nytt lösenord").fill(chosenPassword);
    await newUser.getByRole("button", { name: "Byt lösenord" }).click();

    await expect(newUser).toHaveURL(/\/login\?message=password_changed/, { timeout: 15_000 });
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
    await expect(newUser.getByRole("alert")).toBeVisible({ timeout: 15_000 });
    await expect(newUser).toHaveURL(/\/login/);
  } finally {
    await context.close();
  }

  await page.goto(`/admin/users?search=${encodeURIComponent(email)}`);
  const settled = page.getByRole("row", { name: new RegExp(email) });
  await expect(settled).toBeVisible();
  await expect(settled.getByText("Engångslösenord", { exact: true })).toHaveCount(0);
});
