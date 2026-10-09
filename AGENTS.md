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
