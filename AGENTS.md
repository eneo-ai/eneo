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
