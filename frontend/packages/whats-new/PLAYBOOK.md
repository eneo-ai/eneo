# What's new — playbook

`releases.json` is the single source for the **What's new** page in the app
(`/whats-new`) and the release notes page on docs.eneo.ai. It is written for
the people who use Eneo — case workers, administrators — not for developers.
Developer-facing notes belong in the GitHub release.

This file is the recipe. It is written so that an AI coding assistant can run
it end to end; a human reviews the result.

## 1. Capture at PR time (every contributor, ~1 minute)

The pull request template has a `## User-facing` section. Fill it in for
anything a user can see or do differently after the change:

- Write one or two sentences **from the user's point of view**. "You can now
  change your password under My account", not "Add PATCH /users/me/password".
- Write `No` when nothing changes for users (refactors, CI, dependencies,
  internal admin tooling that has no screen).
- Add the `user-facing` label to the PR.
- If the feature has a natural place to point at, give the element a
  `data-tour="<kebab-case-anchor>"` attribute in the same PR. That is what the
  **Show me** button spotlights. Put the attribute on the row or section, not
  on the button inside it — it survives redesigns better. For a whole page,
  pass `tour="<anchor>"` to its `<Page.Title>`; the check script recognises
  both spellings.

**When does an entry deserve Show me?** When the user would otherwise ask
"where is that?": a new admin page, a new section on a settings page, a
setting the entry tells them to change. Not for changes they meet in the
flow anyway (a better sign-in page, a chat behaviour, a fix), and not when
the target needs an id from the user's own data (a specific assistant or
space) — `href` must be a fixed path.

When an assistant opens the PR it fills this in from the diff; the author
corrects it. Context is cheap at PR time and expensive at release time.

## 2. Draft the release entry (assistant, at release time)

Run this when the release branch is cut or the tag is about to be pushed.

1. Collect the raw material. Only PRs labelled `user-facing` merged since the
   previous release tag:

   ```bash
   PREV=$(git describe --tags --abbrev=0 --match 'v*' origin/develop)
   gh pr list --state merged --base develop --label user-facing \
     --search "merged:>$(git log -1 --format=%cI "$PREV")" \
     --json number,title,body,labels --limit 200
   ```

   Use the `## User-facing` section of each body. Fall back to the title and
   the `## Changes` section only when the section is missing, and say so in
   the PR that adds the entry.

2. Write one entry per PR (merge PRs that describe the same feature) into a
   new release object at the **top** of `releases` in `releases.json`:

   | Field      | Rule                                                                                                                       |
   | ---------- | -------------------------------------------------------------------------------------------------------------------------- |
   | `version`  | Semver without `v`, matching the tag (`v2.3.0` → `2.3.0`).                                                                 |
   | `date`     | Leave out in the draft; set `YYYY-MM-DD` when the tag is pushed.                                                           |
   | `id`       | Stable kebab-case, unique within the release. Never rename after publishing — it is the deep-link target on docs.          |
   | `type`     | `new` (could not do before), `improved` (could, now better), `fixed` (was broken for users).                               |
   | `area`     | Where the user meets it: `chat`, `assistants`, `knowledge`, `spaces`, `skills`, `account`, `admin`, `platform`.            |
   | `audience` | `admin` when only administrators can see the screen. Omit otherwise. Hidden from non-admins in the app.                    |
   | `title`    | ≤ 60 characters, verb first ("Change your own password"). Both `en` and `sv`.                                              |
   | `body`     | 1–3 sentences. What the user can do now and where. Both `en` and `sv`.                                                     |
   | `showMe`   | Optional. `href` is the app path without locale prefix; `anchor` must exist as `data-tour="…"` in `frontend/apps/web/src`. |

3. Editorial rules — the check script enforces the mechanical ones:

   - User perspective, present tense, second person ("you").
   - No PR numbers, issue numbers, class names, endpoint paths, file names,
     migration ids or internal feature-flag names in the text.
   - Name screens the way the UI names them ("My account", "Mitt konto").
   - Swedish is not a translation of English: write both as a Swede would
     read them. Keep product nouns (Skill, Space) as the UI shows them.
   - Skip what users will not notice. Five good entries beat fifteen.
   - Do not claim what you cannot see in the PR. If unsure, ask the author.

4. Validate and open a PR:

   ```bash
   python3 scripts/check_whats_new.py --repo-root .
   cd frontend && bun run --filter @eneo/whats-new format
   ```

   Title the PR `docs(whats-new): draft release notes for vX.Y.Z` and label
   it `user-facing`. The reviewer is the release owner.

## 3. Review (release owner, 15–30 minutes)

Read it as a user would. Cut, reorder, sharpen. Set `date`. Merge before the
tag is pushed so the release image ships with its own notes.

## Maintenance

**Single sources.** `releases.schema.json` owns the shape and the closed
vocabularies (`type`, `area`, `audience`, locales, patterns). Everything
else derives from it or is checked against it:

| What                        | Where                                            | Guarded by                                                  |
| --------------------------- | ------------------------------------------------ | ----------------------------------------------------------- |
| Vocabularies at runtime     | `src/index.js` (`ENTRY_TYPES`, `ENTRY_AREAS`, …) | read from the schema                                        |
| TypeScript unions           | `src/index.d.ts`                                 | `apps/web/.../labels.test.ts` (label maps == schema enums)  |
| Labels in the app (sv/en)   | `apps/web/src/lib/features/whats-new/labels.ts`  | typed exhaustively + the same test                          |
| Labels on docs.eneo.ai (en) | `apps/docs-site/src/components/ReleaseNotes.tsx` | typed exhaustively; unknown values render raw, never crash  |
| Content rules               | `scripts/check_whats_new.py`                     | CI (frontend job) + `scripts/tests/test_check_whats_new.py` |
| Backend version pattern     | `backend/src/eneo/whats_new/whats_new_models.py` | mirrors the schema's `version` pattern; unit test           |

**Adding an area or type.** Edit the enum in `releases.schema.json`, add the
member to the union in `src/index.d.ts`, add a label to `labels.ts` (+ the
`whats_new_area_*` message in both catalogs) and to `ReleaseNotes.tsx`. The
web test suite fails until all four agree.

**Removing or moving UI.** If a redesign drops a `data-tour` attribute or a
route that a `showMe` points at, CI fails with the exact entry. Either
restore the attribute/route or delete that entry's `showMe` in the same PR.
Never leave a dead "Show me" button.

**Correcting a published entry.** Edit the text in place. Keep the `id`: it
is the deep-link target on docs.eneo.ai and may be bookmarked. If a release
had no user-facing changes, add nothing — the app compares by order, not by
equality, so users are not re-notified.

**Data.** `whats_new_state` holds one row per user: `user_id`, the release
id last opened (`seen_version`), the release id last announced
(`announced_version`) and `created_at`/`updated_at`. No content, no free
text. Rows cascade on user deletion. There is nothing to purge on a
retention schedule.

**Growth.** All releases stay in `releases.json` and ship in the web bundle
(roughly 1 kB per entry). Revisit the app page's rendering (paginate or cap
at the last N releases) when the file passes a few hundred entries; the
docs page should always show the full history.

**Ownership.** The release owner reviews the entry; the PR author owns the
`User-facing` section and anchors; anyone changing the schema owns the four
places listed above.

## How the app uses this file

- The backend keeps two markers per user (`GET /api/v1/whats-new/state/`):
  **seen** (`PUT …/seen/`), the newest release the user has opened the page
  for, and **announced** (`PUT …/announced/`), the newest release they have
  been shown the one-time toast for. The profile menu shows a dot while
  `releases[0].version` is newer than the seen marker, and the dot clears
  when the user opens `/whats-new`.
- **Announcement.** On the first app load after a release reaches the user,
  a persistent toast names the first three visible entry titles ("and N
  more") with a link to the page. It is recorded as announced when shown,
  once per user across devices; closing it does not touch the seen marker,
  so the dot stays until they actually look. There is no modal by design.
- "Unseen" means `releases[0].version` is **newer** (semver) than the seen
  version, so a rollback or an older frontend pod during a rolling deploy
  does not re-light the dot. No coupling to the deployed version number:
  whatever `releases[0]` is in the shipped bundle is "current". A hotfix
  release without user-facing changes therefore needs no entry.
- **Show me** navigates to `href` and spotlights `[data-tour=anchor]` with a
  single driver.js step. If the anchor is not on the page (permissions,
  feature flags) the button only navigates.
- Release notes on docs.eneo.ai render the English text from the same file.

## Backports

A patch release cut from `release/vX.Y` carries its own notes on that
branch. Cherry-pick the `releases.json` change to `develop` in the same PR
flow so the file stays a complete history.
