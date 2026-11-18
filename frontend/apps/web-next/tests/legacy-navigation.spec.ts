import { expect, test } from "./csp";

test("redirects an English legacy link while preserving its query and inherited fragment", async ({
  page,
  context
}) => {
  await page.goto("/whats-new");
  await context.addCookies([
    { name: "eneo_locale", value: "sv", url: new URL("/", page.url()).href }
  ]);
  const redirected = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/en/news"
  );
  await page.goto("/en/news?tag=a%2Fb&tag=two#entry");
  const response = await redirected;
  const headers = await response.allHeaders();
  expect(response.status()).toBe(308);
  expect(headers.location).toBe("/whats-new?tag=a%2Fb&tag=two");
  expect(headers["cache-control"]).toBe("no-store");
  const current = new URL(page.url());
  expect(current.pathname).toBe("/whats-new");
  expect(current.search).toBe("?tag=a%2Fb&tag=two");
  expect(current.hash).toBe("#entry");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "What's new", exact: true })).toBeVisible();
  expect((await context.cookies()).find((cookie) => cookie.name === "eneo_locale")?.value).toBe(
    "en"
  );
});

test("hands over cookie and stored language preferences before rendering without a reload", async ({
  page,
  context
}) => {
  await page.goto("/whats-new");
  const cookieUrl = new URL("/", page.url()).href;
  await context.clearCookies({ name: "eneo_locale" });
  await context.addCookies([{ name: "PARAGLIDE_LOCALE", value: "en", url: cookieUrl }]);
  await page.evaluate(() => localStorage.setItem("language", "sv"));
  const legacy = await page.goto("/whats-new");
  const headers = await legacy?.allHeaders();
  expect(legacy?.status()).toBe(200);
  expect(headers?.["set-cookie"]?.includes("eneo_locale=en;")).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  expect(await page.evaluate(() => localStorage.getItem("language"))).toBe("sv");
  expect(
    (await context.cookies()).find((cookie) => cookie.name === "PARAGLIDE_LOCALE")?.value
  ).toBe("en");

  await context.clearCookies({ name: "eneo_locale" });
  await context.clearCookies({ name: "PARAGLIDE_LOCALE" });
  await page.evaluate(() => localStorage.setItem("language", "en"));
  const documents: string[] = [];
  page.on("request", (request) => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
      documents.push(request.url());
    }
  });
  const stored = await page.goto("/whats-new");
  expect(await stored?.text()).toMatch(/<html[^>]*lang="sv"/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "What's new", exact: true })).toBeVisible();
  expect(documents).toHaveLength(1);
  expect((await context.cookies()).find((cookie) => cookie.name === "eneo_locale")?.value).toBe(
    "en"
  );
  expect(await page.evaluate(() => localStorage.getItem("language"))).toBe("en");
});
