import {
  expect,
  test as base,
  type BrowserContext,
  type Cookie,
  type Page
} from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";
import { E2E_CREDENTIALS } from "./helpers";

const SESSION_COOKIES = /^(eneo_web|__Host-eneo_web)$/;
const SAME_ORIGIN = { "Sec-Fetch-Site": "same-origin" };

/** Collects in `violations` what the policy blocks on every page of `context`. */
export async function watchCsp(context: BrowserContext, violations: string[]) {
  await context.exposeBinding("__eneoCspViolation", (_source, violation: string) => {
    violations.push(violation);
  });
  await context.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      const report = (window as unknown as { __eneoCspViolation?: (text: string) => void })
        .__eneoCspViolation;
      report?.(
        `${event.effectiveDirective} blocked ${event.blockedURI || "inline"} ` +
          `(${event.sourceFile || location.href}:${event.lineNumber})`
      );
    });
  });
}

/**
 * Playwright's `test`, failing any test during which a page broke the
 * Content-Security-Policy served by FastAPI. Production allows <style> only with
 * the request nonce: a library that injects styles at runtime (Sonner did,
 * Astryx CodeBlock does) is blocked there and renders unstyled, while the
 * dev server's looser policy hides it. CI runs the specs against the
 * production build, so a violation fails the run instead of only logging a
 * console error.
 *
 * Every page and frame of the test's browser context reports the browser's
 * `securitypolicyviolation` events. A test that provokes one on purpose reads
 * and empties `cspViolations`.
 *
 * Specs use it by importing from here instead of from "@playwright/test":
 * `import { expect, test } from "./csp";`
 *
 * Every test also shares one browser session (auth.setup.ts), and sign-out
 * revokes a session on the server. A test that ends its session (signs out,
 * switches organisation) names `ownSession` to sign in a session of its own
 * first; `ownSession.cookies()` reads that session's cookie. Before and after
 * each test, `sharedSession` checks that the shared session still
 * authenticates, so a test that ended it fails itself and the tests after it
 * fail at once instead of timing out.
 */
export const test = base.extend<{
  cspViolations: string[];
  ownSession: { cookies: () => Promise<Cookie[]> };
  sharedSession: void;
}>({
  // Wait for React to mount before interacting with the page.
  // `run`, not `use`: the hooks lint rule would treat use(page) as a hook.
  page: async ({ page }, run) => {
    const mounted = () =>
      page.waitForFunction(
        () => {
          const first =
            document.querySelector("#main-content > *") ??
            document.querySelector("#root > *") ??
            document.body.firstElementChild;
          return !!first && Object.keys(first).some((key) => key.startsWith("__reactFiber$"));
        },
        undefined,
        { timeout: 15_000 }
      );
    const goto = page.goto.bind(page);
    const reload = page.reload.bind(page);
    page.goto = async (...args: Parameters<Page["goto"]>) => {
      const response = await goto(...args);
      await mounted();
      return response;
    };
    page.reload = async (...args: Parameters<Page["reload"]>) => {
      const response = await reload(...args);
      await mounted();
      return response;
    };
    await run(page);
  },
  cspViolations: [
    async ({ context }, use) => {
      const violations: string[] = [];
      await watchCsp(context, violations);
      await use(violations);
      expect(violations, "Content-Security-Policy violations").toEqual([]);
    },
    { auto: true }
  ],
  // The password sign-in the login page makes, in place of the shared cookie.
  ownSession: async ({ context }, run) => {
    await context.clearCookies({ name: SESSION_COOKIES });
    const signIn = await context.request.post("/api/v1/auth/session/password/", {
      form: E2E_CREDENTIALS,
      headers: SAME_ORIGIN
    });
    expect(signIn.status(), "The test's own sign-in").toBe(204);
    await run({
      cookies: async () =>
        (await context.cookies()).filter((cookie) => SESSION_COOKIES.test(cookie.name))
    });
  },
  sharedSession: [
    async ({ playwright, baseURL }, run) => {
      const shared = await playwright.request.newContext({ baseURL, storageState: STORAGE_STATE });
      const authenticates = async () =>
        (await shared.get("/api/v1/auth/session/", { headers: SAME_ORIGIN })).status() === 204;
      try {
        expect(
          await authenticates(),
          "The suite's shared session (auth.setup.ts) ended before this test"
        ).toBe(true);
        await run();
        expect(
          await authenticates(),
          "This test ended the suite's shared session: a test that ends its session uses ownSession"
        ).toBe(true);
      } finally {
        await shared.dispose();
      }
    },
    { auto: true }
  ]
});

export { expect };
