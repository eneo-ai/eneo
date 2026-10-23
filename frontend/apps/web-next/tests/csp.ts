import { expect, test as base, type Page } from "@playwright/test";

/**
 * Playwright's `test`, failing any test during which a page broke the
 * Content-Security-Policy (src/proxy.ts). Production allows <style> only with
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
 */
export const test = base.extend<{ cspViolations: string[] }>({
  // The server's HTML shows before React attaches its handlers: the shell
  // hydrates first and the page (the (app) loading boundary) after it, and a
  // click on the page before that goes nowhere (React can't hydrate a part
  // whose code hasn't loaded yet, so it drops the click). goto and reload wait
  // until the page's first element, or the body's on a page without the
  // shell, carries the `__reactFiber$…` property React DOM gives the elements
  // it has hydrated.
  // `run`, not `use`: the React hooks lint rule reads `use(page)` as a hook call.
  page: async ({ page }, run) => {
    const hydrated = () =>
      page.waitForFunction(
        () => {
          const first =
            document.querySelector("#main-content > *") ?? document.body.firstElementChild;
          return !!first && Object.keys(first).some((key) => key.startsWith("__reactFiber$"));
        },
        undefined,
        { timeout: 15_000 }
      );
    const goto = page.goto.bind(page);
    const reload = page.reload.bind(page);
    page.goto = async (...args: Parameters<Page["goto"]>) => {
      const response = await goto(...args);
      await hydrated();
      return response;
    };
    page.reload = async (...args: Parameters<Page["reload"]>) => {
      const response = await reload(...args);
      await hydrated();
      return response;
    };
    await run(page);
  },
  cspViolations: [
    async ({ context }, use) => {
      const violations: string[] = [];
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
      await use(violations);
      expect(violations, "Content-Security-Policy violations").toEqual([]);
    },
    { auto: true }
  ]
});

export { expect };
