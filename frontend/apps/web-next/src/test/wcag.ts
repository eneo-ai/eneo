/**
 * The axe-core rule tags for web-next's required level, WCAG 2.2 A + AA
 * (ACCESSIBILITY.md). Shared by the Vitest helper (src/test/axe.ts) and the
 * Playwright page scans (tests/a11y.spec.ts) so both check the same rules.
 * Keep this file free of imports: Playwright loads it outside the Next build.
 */
export const WCAG_22_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
