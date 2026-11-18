/**
 * What both axe checks share: the Vitest helper (src/test/axe.ts) and the
 * Playwright page scans (tests/a11y.spec.ts) test the same rules and accept
 * exceptions on the same terms (ACCESSIBILITY.md → Exceptions).
 * Keep this file free of imports: Playwright loads it outside the Next build.
 */

/** The axe-core rule tags for web-next's required level, WCAG 2.2 A + AA. */
export const WCAG_22_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/**
 * What the browser scans (tests/a11y.spec.ts, tests/a11y-routes.spec.ts) switch on beyond the
 * WCAG tags. axe leaves these out of a tag run: they are best-practice or experimental rules that
 * find real structure faults (a paragraph styled as a heading, a table without header cells, two
 * landmarks of one kind with no name, an empty heading or header cell, a scope on the wrong cell).
 * The first three are ACCESSIBILITY.md rule 1: one main landmark, an h1, headings in order.
 * `label-content-name-mismatch` is axe's experimental check of WCAG 2.5.3 Label in Name (rule 8):
 * a control named by aria-label holds what it shows, in order. It joins text in separate spans
 * with no separator, so words that sit in different spans need a space between them.
 */
export const AXE_PAGE_RULES = [
  "page-has-heading-one",
  "landmark-one-main",
  "heading-order",
  "p-as-heading",
  "td-has-header",
  "table-fake-caption",
  "landmark-unique",
  "empty-heading",
  "empty-table-header",
  "scope-attr-valid",
  "label-content-name-mismatch"
];

/** An issue reference: a URL, `#1234` or `owner/repo#1234`. */
const ISSUE_LINK = /https?:\/\/\S+|(?<![\w/])(?:[\w.-]+\/[\w.-]+)?#\d+\b/;

/**
 * Throws unless every exception (what is skipped → why) gives a reason and
 * an issue link: an undocumented exception is a silent pass.
 *
 * @param describe Names what an entry skips, e.g. `(rule) => \`Skipping the axe rule "${rule}"\``.
 * @example assertDocumented({ "aria-allowed-role": "Upstream Astryx bug, see #1234" }, describe)
 */
export function assertDocumented(
  exceptions: Record<string, string>,
  describe: (key: string) => string
): void {
  for (const [key, reason] of Object.entries(exceptions)) {
    const hasIssue = ISSUE_LINK.test(reason);
    const hasReason = /\p{L}{3}/u.test(reason.replace(ISSUE_LINK, ""));
    if (!hasIssue || !hasReason) {
      throw new Error(
        `${describe(key)} needs a reason and an issue link ` +
          `(ACCESSIBILITY.md → Exceptions); got ${JSON.stringify(reason)}.`
      );
    }
  }
}
