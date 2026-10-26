import { expect, test } from "@playwright/test";

test("logging out invalidates the authenticated session", async ({ page }) => {
  await page.goto("/");
  await page.locator('header nav button[aria-haspopup="menu"]').last().click();
  await page.getByRole("menuitem", { name: /^(Logga ut|Logout)$/ }).click();

  await expect(page).toHaveURL(/\/login\?.*message=logout/);
  await expect(page.locator('input[name="email"]')).toBeVisible();

  await page.goto("/");

  await expect(page).toHaveURL(/\/login/);
  await expect(page.locator('input[name="password"]')).toBeVisible();
});

test("resource requests and forged form submissions cannot log out the user", async ({ page }) => {
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const authCookies = async () =>
    (await page.context().cookies(origin)).filter(
      (cookie) => cookie.name === "auth" || cookie.name === "acc"
    );
  const before = await authCookies();
  expect(before.some((cookie) => cookie.name === "auth")).toBe(true);

  for (const path of [
    "/logout",
    "/logout?message=expired",
    "/login?clear_cookies=true",
    "/embed/unknown?clear_cookies=1",
    "/login/switch-organisation"
  ]) {
    await page.request.get(`${origin}${path}`, { headers: { accept: "image/*" }, maxRedirects: 0 });
    expect(await authCookies()).toEqual(before);
  }

  const forgedHeaders: Record<string, string>[] = [
    { "content-type": "application/x-www-form-urlencoded", origin: "https://attacker.invalid" },
    { "content-type": "application/x-www-form-urlencoded" }
  ];
  for (const action of ["logout", "clearCookies", "switchOrganisation"]) {
    for (const headers of forgedHeaders) {
      const response = await page.request.post(`${origin}/logout?/${action}`, {
        headers,
        data: "",
        maxRedirects: 0
      });
      expect(response.status()).toBe(403);
      expect(await authCookies()).toEqual(before);
    }
  }
});
