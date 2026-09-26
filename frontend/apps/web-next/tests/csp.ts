import { expect, test as base } from "@playwright/test";

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
