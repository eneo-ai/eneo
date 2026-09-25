import axe from "axe-core";
import { WCAG_22_AA_TAGS } from "./wcag";

/**
 * Rules jsdom cannot evaluate: it has no layout or rendering, so every element
 * is 0×0 and has no computed colours. They are checked elsewhere instead:
 * - `color-contrast`, `link-in-text-block`: colour pairs are enforced on the
 *   design tokens by src/theme/eneo-theme.contrast.test.ts, and on real pages
 *   by tests/a11y.spec.ts.
 * - `target-size` (WCAG 2.5.8): measured on real pages by tests/a11y.spec.ts.
 */
const JSDOM_UNSUPPORTED_RULES = ["color-contrast", "link-in-text-block", "target-size"];

export type AxeCheckOptions = {
  /**
   * Rules to skip for this check, each with the reason and the issue that
   * tracks the fix (ACCESSIBILITY.md → Exceptions). Prefer fixing the markup.
   *
   * @example { "aria-allowed-role": "Upstream Astryx bug, see #1234" }
   */
  disableRules?: Record<string, string>;
};

function describeViolation(violation: axe.Result): string {
  const nodes = violation.nodes
    .map(
      (node) =>
        `    ${node.target.join(" ")}\n      ${node.failureSummary?.replace(/\n/g, "\n      ")}`
    )
    .join("\n");
  return `${violation.id} (${violation.impact ?? "unknown"}): ${violation.help}\n  ${violation.helpUrl}\n${nodes}`;
}

/**
 * Runs axe-core with the WCAG 2.2 A/AA rules against a rendered component and
 * fails with a readable report for every violation. Needs the jsdom test
 * environment (`// @vitest-environment jsdom` at the top of the test file).
 *
 * Pass `document.body` to include portalled content (open menus, dialogs).
 *
 * @example
 * const { container } = render(<PageHeader title="Ytor" />);
 * await expectNoAxeViolations(container);
 */
export async function expectNoAxeViolations(
  container: Element | Document = document.body,
  options: AxeCheckOptions = {}
): Promise<void> {
  const disabled = [...JSDOM_UNSUPPORTED_RULES, ...Object.keys(options.disableRules ?? {})];
  const results = await axe.run(container, {
    runOnly: { type: "tag", values: WCAG_22_AA_TAGS },
    rules: Object.fromEntries(disabled.map((rule) => [rule, { enabled: false }])),
    resultTypes: ["violations"]
  });
  if (results.violations.length > 0) {
    throw new Error(
      `axe found ${results.violations.length} WCAG 2.2 A/AA violation(s):\n\n` +
        results.violations.map(describeViolation).join("\n\n")
    );
  }
}
