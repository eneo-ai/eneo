import axe from "axe-core";
import { assertDocumented, WCAG_22_AA_TAGS } from "./wcag";

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
   * Rules to skip for this check, each with the reason and a link to the
   * issue that tracks the fix (ACCESSIBILITY.md → Exceptions): a URL or an
   * issue number (`#1234`). Prefer fixing the markup.
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
  assertDocumented(options.disableRules ?? {}, (rule) => `Skipping the axe rule "${rule}"`);
  const disabled = [...JSDOM_UNSUPPORTED_RULES, ...Object.keys(options.disableRules ?? {})];
  // jsdom frames have no document axe can message, so the run would throw on
  // the first <iframe>; embedded pages are checked by their own tests.
  const results = await axe.run(container, {
    iframes: false,
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

/** What axe ignores when it compares a name with a label: case, its punctuation set and runs of white space. */
function curate(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ -⁯⸀-⹿\\'!"#$%&£¢¥§€()*+,\-./:;<=>?@[\]^_`{|}~±]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * WCAG 2.5.3 Label in Name as axe's label-content-name-mismatch checks it in the browser scans
 * (tests/a11y.spec.ts, tests/a11y-routes.spec.ts); jsdom cannot run that rule (no CSS hides
 * `sr-only` text). Throws unless a control named by `aria-label` or `aria-labelledby` has an
 * accessible name, `name` (as the test found it by), that holds what the control shows, in order.
 * Shown text is read as axe reads it: text nodes joined with no separator (so words in separate
 * spans need a space between them), `aria-hidden` text counted, `sr-only` text left out. A
 * control named by its content passes: the rule does not apply to it.
 *
 * @example
 * const name = "Verktyg: 2 av 3 aktiva";
 * expectNameToHoldVisibleText(screen.getByRole("button", { name }), name);
 */
export function expectNameToHoldVisibleText(control: Element, name: string): void {
  if (!control.hasAttribute("aria-label") && !control.hasAttribute("aria-labelledby")) return;
  const shown = control.cloneNode(true) as Element;
  shown.querySelectorAll(".sr-only").forEach((node) => node.remove());
  const visible = curate(shown.textContent ?? "");
  if (!curate(name).includes(visible)) {
    throw new Error(
      `The name "${name}" does not hold what the control shows, "${visible}", in order (WCAG 2.5.3).`
    );
  }
}
