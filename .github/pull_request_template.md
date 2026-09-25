## Changes
<!-- What did you change? For documentation, follow frontend/apps/docs-site/AUTHORING.md and state the target release line and page (or why docs are unaffected). -->

## Why
<!-- Why was this needed? -->

## Planning
<!-- Link the development task this PR closes. The task owns the parent epic link. -->

- Task: Fixes #

## User-facing
<!-- One or two sentences from the user's point of view, or "No".
     Feeds the What's new page at release time — see frontend/packages/whats-new/PLAYBOOK.md.
     Give anything worth pointing at a data-tour="..." anchor. -->

## Testing
<!-- How did you test this? -->

## Accessibility
<!-- Required when the PR changes UI; otherwise write "No UI change".
     Standard: WCAG 2.2 AA, see frontend/apps/web-next/ACCESSIBILITY.md. -->

- [ ] Meets WCAG 2.2 AA: keyboard operable with visible, unobscured focus; names and labels from i18n; errors in text; status messages announced; colour never the only signal; targets at least 24×24 px
- [ ] Automated checks pass: `bun run lint` (jsx-a11y, `eneo/*` rules), `bun run test` (axe, contrast), axe page scans (`tests/a11y.spec.ts`)
- [ ] Checked by hand: keyboard only, screen reader (VoiceOver or NVDA), 200%/400% zoom, reduced motion, light and dark mode
- [ ] No new lint suppressions or axe exclusions (fixed ones pruned from `eslint-suppressions.json`)

## Screenshots
<!-- If UI changes, add before/after -->
