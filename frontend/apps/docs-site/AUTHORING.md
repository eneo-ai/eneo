# Put documentation with the behaviour it describes

This is the shared authoring rule for contributors and coding agents. Start
with the intended product version, then find the existing page in
[DOCS_MAP.md](DOCS_MAP.md). Version folders are generated; authors do not move
pages when a release is cut.

## Choose the branch and source

| Change                                           | Target branch                            | Edit                                                                                |
| ------------------------------------------------ | ---------------------------------------- | ----------------------------------------------------------------------------------- |
| New or changed behaviour for the next release    | `develop`, in the same PR as the code    | The existing `src/content/**/*.mdx` page; add a page only for a new subject         |
| Incorrect instructions for a released product    | That product's `release/vX.Y` branch     | The page on that branch; port the correction to `develop` if still applicable       |
| User-facing announcement of a change             | The branch on which the change will ship | `frontend/packages/whats-new/releases.json`, following that package's `PLAYBOOK.md` |
| Navigation, theme or version-publication changes | `develop`                                | Site components or scripts; these apply to every published version                  |
| Contributor/repository procedures                | `develop`                                | The existing repository guide; link to it rather than duplicating it                |

A bug fix targeted at a release branch should carry its matching documentation
and user-facing notes on that branch. An unreleased feature belongs on
`develop` even when its planned version number is already known. Never copy
instructions for a new feature into an older release just to make them visible
on the site's front page.

For What's new, reuse an existing entry or add one under the intended release;
do not choose a release by whatever happens to be first in the file. The
package's PLAYBOOK owns entry shape, translations and release dates. Its
`releases.json` is the source for both the app and the documentation's release
notes component. MDX explains how to use a feature; it does not duplicate the
announcement. On branches predating that package, ordinary documentation fixes
remain possible without introducing a release-notes package.

## Examples

- **A new storage policy will ship in the next release:** change its existing
  guide on `develop`, alongside the implementation. Add the brief user-facing
  announcement to that release in `releases.json`. The guide is visible in
  `/dev/` until a final tag selects its release line.
- **An environment variable is misspelled in the 2.1 installation guide:** fix
  `src/content/guides/deployment.mdx` on `release/v2.1`, then port the correction
  to `develop`. Do not add `src/content/v2.1/`.
- **Linking an app feature to its documentation:** use
  `https://docs.eneo.ai/v2.2/guides/<page>` for the 2.2 line. That address remains
  the same when 2.3 becomes stable. `/` follows the latest stable version;
  `/dev/` deliberately follows unreleased work.

## Before opening the PR

1. Verify the described behaviour against code on the **target branch**.
2. Use the map to update the existing canonical page. New pages need a map
   entry and, when ordered navigation matters, the appropriate `_meta.ts` entry.
3. State the target release line, affected page and user-facing impact in the
   PR. If neither docs nor release notes need an update, say why.
4. Run the focused checks allowed by your environment. Locally on the shared
   Mac, use the global resource supervisor; full builds and browser checks need
   explicit authorization. CI runs the publication contract tests and builds every selected
   version in the PR. The publication job validates every selected version before deploying.

The tests ensure that each version uses its own content and release notes,
that a failed version cannot remove an existing publication, and that version
URLs remain stable. Hand-authored `src/content/vX.Y` folders are rejected. They cannot determine whether prose accurately describes a
feature; target-branch review remains necessary.

## Release and publication

The resolver derives version lines from final Git tags, excluding RCs, and
pins each selected release branch to a commit for that build. It uses the tag
when a release branch no longer exists. All versions, including stable, have
`/vX.Y/` addresses; root-page links redirect to the latest stable equivalent.
Only the configured number of previous release lines is retained. An address
is permanent while its line is supported; deliberate retirement can remove it.

Documentation and What's new updates on `develop` trigger publication. A
successful existing CI or image-publishing workflow on a pushed ref also
triggers central reconciliation on `develop`, including older release branches.
An hourly scheduled reconciliation catches refs whose old workflows did not
run; GitHub may delay scheduled jobs. Unchanged inputs skip installation and
builds. A manual run can force a rebuild. See [README.md](README.md) for the
implementation and recovery procedure.
