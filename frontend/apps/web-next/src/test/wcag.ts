/**
 * What both axe checks share: the Vitest helper (src/test/axe.ts) and the
 * Playwright page scans (tests/a11y.spec.ts) test the same rules and accept
 * exceptions on the same terms (ACCESSIBILITY.md → Exceptions).
 * Keep this file free of imports: Playwright loads it outside the Next build.
 */

/** The axe-core rule tags for web-next's required level, WCAG 2.2 A + AA. */
export const WCAG_22_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

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
