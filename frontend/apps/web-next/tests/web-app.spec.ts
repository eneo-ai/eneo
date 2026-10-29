import AxeBuilder from "@axe-core/playwright";
import { LOCALE_COOKIE } from "../src/lib/i18n/locales";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import { expect, test } from "./csp";
import { E2E_CREDENTIALS } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

const LOGIN = "/login?showUsernameAndPassword=true";
const SESSION = "/api/v1/auth/session/";
const GENERATION = "Eneo-Session-Generation";
const SAME_ORIGIN = { "Sec-Fetch-Site": "same-origin" };

test.describe("web app boot", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const [cookie, locale] of [
    ["en", "en"],
    ["de", "sv"],
    [undefined, "sv"]
  ] as const) {
    test(`boots with ${cookie ?? "no"} locale cookie`, async ({
      context,
      baseURL,
      cspViolations
    }) => {
      if (cookie) await context.addCookies([{ name: LOCALE_COOKIE, value: cookie, url: baseURL! }]);
      // A raw page also lets the failure test inspect HTML before React starts.
      // The shared context still collects and asserts all CSP violations.
      const page = await context.newPage();
      let configRequests = 0;
      page.on("request", (request) => {
        if (new URL(request.url()).pathname === "/api/v1/runtime-config") configRequests++;
      });
      const response = await page.goto(LOGIN);
      await expect(page.locator('input[name="email"]')).toBeVisible();
      expect(response?.status()).toBe(200);
      const headers = response!.headers();
      const nonce = headers["content-security-policy"]?.match(/'nonce-([^']+)'/)?.[1];
      expect(nonce).toBeTruthy();
      expect(headers["cache-control"]).toBe("no-store");
      expect(configRequests).toBe(1);
      expect(
        await page.evaluate(() => ({
          locale: document.documentElement.lang,
          meta: document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce,
          global: globalThis.__webpack_nonce__,
          placeholders: document.documentElement.outerHTML.includes("__ENEO_")
        }))
      ).toEqual({ locale, meta: nonce, global: nonce, placeholders: false });
      const mismatches = await page
        .locator('head script[src], style, link[rel="stylesheet"], link[rel="modulepreload"]')
        .evaluateAll(
          (elements, expected) =>
            elements
              .filter((element) => (element as HTMLElement).nonce !== expected)
              .map((element) => element.tagName),
          nonce
        );
      expect(mismatches, "Executable scripts and styles must carry the response nonce").toEqual([]);
      const reload = await page.reload();
      await expect(page.locator('input[name="email"]')).toBeVisible();
      expect(reload!.headers()["content-security-policy"]).not.toContain(`'nonce-${nonce}'`);
      expect(configRequests).toBe(2);
      expect(cspViolations).toEqual([]);
    });
  }

  test("configuration failure stays accessible and reload recovers", async ({
    context,
    cspViolations
  }) => {
    const page = await context.newPage();
    await page.route("**/api/v1/runtime-config", (route) => route.abort());
    await page.goto(LOGIN);
    await expect(page.locator('h1[lang="sv"]')).toBeVisible();
    await expect(page.locator('p[lang="en"]')).toContainText("Eneo could not start");
    await expect(page).toHaveTitle("Eneo");
    expect(
      await page
        .locator("#root")
        .evaluate((root) => Object.keys(root).some((key) => key.startsWith("__reactContainer$")))
    ).toBe(false);
    type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
    const audit = await new AxeBuilder({ page: page as unknown as AxePage })
      .withTags(WCAG_22_AA_TAGS)
      .analyze();
    expect(audit.violations.map((violation) => violation.id)).toEqual([]);
    await page.unroute("**/api/v1/runtime-config");
    await page.getByRole("link", { name: "Försök igen / Try again" }).click();
    await expect(page.locator('input[name="email"]')).toBeVisible();
    expect(cspViolations).toEqual([]);
  });
});

test("the MCP content origin cannot serve the web app or sign out its session", async ({
  context,
  baseURL
}) => {
  const before = await context.request.get(SESSION, { headers: SAME_ORIGIN });
  expect(before.status()).toBe(204);
  const generation = before.headers()[GENERATION.toLowerCase()];
  expect(generation).toBeTruthy();
  const contentOrigin = new URL(baseURL!);
  contentOrigin.hostname = "127.0.0.1";
  const page = await context.newPage();
  const response = await page.goto(contentOrigin.origin);
  expect(response?.status()).toBe(404);
  await page.setContent('<form method="post"><button type="submit">Submit</button></form>');
  await page.locator("form").evaluate(
    (form, url) => {
      (form as HTMLFormElement).action = url;
    },
    new URL(`${SESSION}logout/`, baseURL).href
  );
  const refused = page.waitForResponse(
    (response) => new URL(response.url()).pathname === `${SESSION}logout/`
  );
  await page.getByRole("button", { name: "Submit" }).click();
  const logout = await refused;
  expect((await logout.request().allHeaders())["sec-fetch-site"]).toBe("cross-site");
  // The outer CORS gate rejects this browser Origin before the session route.
  expect(logout.status()).toBe(400);
  expect((await logout.json()).code).toBe("disallowed_cors_origin");
  expect((await logout.allHeaders())["set-cookie"]).toBeUndefined();
  const after = await context.request.get(SESSION, { headers: SAME_ORIGIN });
  expect(after.status()).toBe(204);
  expect(after.headers()[GENERATION.toLowerCase()]).toBe(generation);
});

test("cookie mutations need an origin while bearer authentication ignores cookies", async ({
  context,
  request
}) => {
  const probe = await context.request.get(SESSION, { headers: SAME_ORIGIN });
  expect(probe.status()).toBe(204);
  const generation = probe.headers()[GENERATION.toLowerCase()] ?? "";
  expect(generation).toBeTruthy();
  const mutation = await context.request.post("/api/v1/users/me/password/", {
    headers: { [GENERATION]: generation },
    data: {}
  });
  expect(mutation.status()).toBe(401);
  const login = await request.post("/api/v1/users/login/token/", { form: E2E_CREDENTIALS });
  expect(login.status()).toBe(200);
  const { access_token: token } = await login.json();
  const me = await request.get("/api/v1/users/me/", {
    headers: {
      Authorization: `Bearer ${token}`,
      Cookie: "__Host-eneo_web=invalid; eneo_web=invalid",
      "Sec-Fetch-Site": "cross-site"
    }
  });
  expect(me.status()).toBe(200);
  expect((await me.json()).email).toBe(E2E_CREDENTIALS.username);
  expect(me.headers()[GENERATION.toLowerCase()]).toBeUndefined();
});
