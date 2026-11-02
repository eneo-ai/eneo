# Frontend development

SvelteKit in `frontend/apps/web` is the primary frontend and the default for
frontend development. Implement ordinary frontend fixes and new features there.
React/Next.js with Astryx in `frontend/apps/web-next` is an optional beta;
work there must be explicitly intended for the beta.

The web-next UI and component rules apply within that app. Follow the existing
Svelte components and patterns when working in `frontend/apps/web`.

# Documentation and release changes

Before changing documented behaviour or documentation, read
[the documentation authoring guide](frontend/apps/docs-site/AUTHORING.md).
It owns the rules for choosing the target branch, page and release notes.
Use [DOCS_MAP.md](frontend/apps/docs-site/DOCS_MAP.md) to find the existing page
before creating one. Update this map when a new documented area is introduced.

Do not put unreleased behaviour on a release branch, edit generated version
folders, or duplicate What's new entries in MDX. Keep the documentation change
with its behaviour change. In the PR, state the intended release line and the
page changed, or explain why documentation is unaffected.

# What's new (in-app release notes)

`frontend/packages/whats-new/releases.json` feeds the What's new page inside
the app and the release-notes page on the docs site. Read
[its playbook](frontend/packages/whats-new/PLAYBOOK.md) before touching it.

An entry describes something a person sees or does differently **inside
Eneo** after the change: a new or changed screen, control, behaviour or
message. Ask that question before writing one; if the answer is no, write
`No` in the PR's `## User-facing` section and add no entry.

Not news, however important: configuration done outside the app (identity
provider claims, environment variables, deployment files, database
migrations), operator-only fixes, performance work, dependency bumps, CI and
tests. Those belong in the GitHub release notes and in the guides on the docs
site. An administrator audience does not change this: an `audience: admin`
entry is for a change an administrator meets in Eneo's own administration
pages.

Put entries for unreleased work in the `next` block on `develop`; a fix that
ships from a release branch gets its notes in that branch's block with the
same id. A hotfix tag needs no block of its own. Order a block for readers:
news for everyone first, administrator-only entries last. The announcement
dialog shows the first entries of the newest release, and tests pin that
order.

# Frontend accessibility

UI work in `frontend/apps/web-next` must meet WCAG 2.2 AA; follow [its accessibility standard](frontend/apps/web-next/ACCESSIBILITY.md).

# GitHub labels

Before creating or updating an issue or pull request, follow the
[required-label policy](.github/PROJECT_WORKFLOW.md#required-labels).
Apply actual GitHub labels, using `gh pr create --label`, `gh pr edit --add-label`,
or the equivalent issue commands; writing label names in the body is insufficient.

- Every PR needs one primary change type and at least one affected area. Choose
  from the existing catalog; do not invent synonyms or use `needs:*` as a substitute.
- Classify the final diff by intent. Do not infer change type solely from the
  branch name, PR title, a generic task template, or a linked epic's labels.
- Add `security`, `accessibility`, and `breaking-change` when their definitions
  apply. Multiple areas are allowed. Recheck labels after a scope change and on
  every backport. Documentation accompanying a fix does not make it docs-only.
- Use issue templates and select Area explicitly. When creating issues through
  the API/CLI, apply their kind/type and area labels yourself. Unknown work stays
  in triage; never fabricate a classification to make a check pass.
- Keep planning status, general priority, and roadmap version in Project fields.
  `kind:*` remains the planning-kind mirror. On PRs, `kind:chore` is also the
  existing label for maintenance; do not add a second `chore` label.
- Verify the **PR labels** check before merging. Bots and backports follow the
  same policy. The canonical executable catalog is
  [.github/scripts/label-policy.mjs](.github/scripts/label-policy.mjs).
