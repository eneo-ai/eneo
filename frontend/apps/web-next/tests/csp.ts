import { expect, test as base, type Page } from "@playwright/test";

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
 */
export const test = base.extend<{ cspViolations: string[] }>({
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
