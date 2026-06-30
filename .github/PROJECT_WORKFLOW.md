# Eneo project workflow

Eneo uses one canonical organization project for product planning:

- Project: https://github.com/orgs/eneo-ai/projects/5
- Owner: `eneo-ai`
- Purpose: roadmap, active development, findings, and review intake in one place

Older projects can remain as historical references while open work is moved into the canonical project.

## Design principles

The project should be easy enough that people actually use it.

- Developers should mainly create or update normal GitHub issues and pull requests.
- Product/project leads should mainly use GitHub Project views.
- Committee views should show outcomes, status, sponsor/municipality, owner/lead, progress, and decisions without requiring people to read implementation detail.
- Automation should keep labels and export metadata useful where practical, but it should not block normal development flow.

## Canonical metadata model

Use one source of truth for humans and keep fallback metadata only for automation/export:

- Human UI/source of truth: GitHub issue type, Parent issue/sub-issues, GitHub Project fields, and GitHub Project views.
- Automation/export fallback: `kind:*` labels and issue body sections.

`kind:*` labels are maintained because they are simple, visible, and reliable for scripts. Do not require a separate Project `Kind` field until it is automatically populated. If Project #5 already has `Kind`, it can remain as an optional convenience field, but it must not become a second manual truth.

## Item kinds

Use one item kind per issue:

- `Epic`: roadmap-level outcome, planned by version, owns development tasks.
- `Task`: buildable development item, must belong to an epic.
- `Bug`: reported product defect. Triage decides whether it becomes planned task work.
- `Finding`: observed issue, risk, or improvement candidate. Findings can stay in the main project.
- `Chore`: maintenance work without direct product behavior.

Use native GitHub issue types where available. GitHub includes default `task`, `bug`, and `feature` issue types at the organization level. Custom types such as `Epic`, `Finding`, or `Initiative` can be added later if the organization wants them, but the current workflow does not require them.

## Versioned roadmap

Epics carry a `Roadmap version` value in the issue body and/or Project field, for example `2.1`, `2.2`, `2.3`, `2.X`, `Future`, or `Unscheduled`.

`Roadmap version` is a release bucket for grouping, filtering, and export. It is not the timeline field for GitHub's Roadmap layout.

Use the version string that is useful for planning. Adding `2.7` or `2.7 RC` should not require a code change; update the issue or Project field value. If Project #5 uses a single-select `Roadmap version` field, add the new option in GitHub Project settings. The issue body remains a free-form export fallback.

GitHub Releases and release-candidate tags are delivery artifacts, not the source of truth for roadmap planning. Use release names such as `2.7 RC` in `Roadmap version` only when the roadmap needs that planning bucket.

For a real GitHub Roadmap timeline, configure one of these in Project #5:

- Recommended for committee/stakeholder roadmap: `Start date` and `Target date` date fields.
- Acceptable for fixed planning cycles: an `Iteration` field.

The Epic issue body has optional `Start date` and `Target date` sections as export fallback, but the GitHub Project fields should be the human-facing source of truth.

Recommended views:

- `Committee Roadmap`: Roadmap layout, filter epics, use `Start date`/`Target date`, slice or group by `Roadmap version`, show `Sponsor / municipality`, `Owner / lead`, `Sub-issue progress`, and `Decision needed`.
- `Standup`: table or board, filter active non-Done tasks and PRs, group by `Parent issue` or status, show assignee and linked PRs.
- `Epics`: table, filter epics, show `Roadmap version`, status, priority, area, sponsor, owner, dates, and progress.
- `Active work`: table or board, filter out `status:Done`.
- `Findings`: table, filter `kind:finding` or optional `Kind:Finding`.
- `Needs triage`: table, filter `label:needs:triage`.
- `Needs epic`: table, filter `label:needs:epic`.
- `Done since last committee`: table, filter epics/tasks done since the last committee meeting date.

## Required GitHub setup

Configure this once after merge:

- Organization project: `eneo-ai/5`.
- Secret: `ADD_TO_PROJECT_PAT`.
- PAT access: enough to add/read organization Project items and read repo issues/PRs used by the export.
- Required issue types: `task`, `bug`, `feature`.
- Optional custom issue types later: `Epic`, `Finding`, `Initiative`.
- Required Project fields: `Status`, `Roadmap version`, `Start date`, `Target date`, `Priority`, `Area`.
- Recommended Project fields: `Owner / lead`, `Sponsor / municipality`, `Decision needed`, `Visibility`.
- Enable hidden Project fields: `Parent issue`, `Sub-issue progress`.
- Required views: `Committee Roadmap`, `Standup`, `Epics`, `Active work`, `Findings`, `Needs triage`, `Needs epic`, `Done since last committee`.

Issue forms also list `projects: ["eneo-ai/5"]` for convenience. If the issue creator lacks write access to the org project, the intake workflow and Project auto-add should still add the item.

## Adding new items

Most new planning work should start manually from the GitHub issue chooser:

1. Open a new issue in `eneo-ai/eneo`.
2. Choose `Epic`, `Development task`, `Finding`, `Bug Report`, or `Feature Request`.
3. Fill in the required fields.
4. Submit the issue. The template and intake workflow add it to the canonical Eneo project.

Use `Epic` when the idea belongs on the roadmap and may contain several implementation tasks. This is the preferred starting point for product planning such as "comes in 2.1" or "comes in 2.2".

Use `Development task` when the work is already scoped enough to build. A task should reference an epic in `Parent epic`, for example `#123`. This is the main planning metadata developers need to keep current.

Use `Finding` when something has been observed but is not yet planned. A finding can later be converted into one or more tasks under an epic.

Use a Project draft item for an initiative that belongs to Eneo as a whole but does not yet belong to a repo. Convert it to an issue once implementation needs tracking in a repo.

AI-assisted development should follow the same model:

1. If AI discovers a follow-up during implementation, create or suggest a `Finding` unless the work is already clearly scoped.
2. If AI is asked to plan new roadmap work, create or suggest an `Epic`.
3. If AI is asked to split an approved epic, create `Development task` issues and link each one to the epic.
4. AI-created tasks must include the parent epic reference in the issue body so automation and exports can resolve the relationship.

Do not create disconnected tasks for roadmap work. If there is no suitable epic, create the epic first and then add tasks under it.

## Epic fields

The Epic template fields have these meanings:

- `Summary`: short non-technical description of the outcome and why it matters.
- `Roadmap version`: release bucket such as `2.1`, `2.2`, `2.3`, `2.X`, `Future`, or `Unscheduled`.
- `Start date`: optional export fallback for the Project `Start date` field.
- `Target date`: optional export fallback for the Project `Target date` field.
- `Sponsor / municipality`: optional requester/sponsor shown in committee roadmap output.
- `Owner / lead`: optional person or team explicitly responsible for driving the epic when it is planned. Roadmap export reads only this field or issue-body section and does not infer owners from labels, areas, assignees, or AI-generated text.
- `Priority`: relative order inside the roadmap version. `P0` is urgent or release-critical; `P3` is lowest priority.
- `Area`: primary ownership area: `Backend`, `Frontend`, `Infra`, `Docs`, `Security`, or `Other`.
- `Flow / architecture`: optional Mermaid graph for the main user flow or system relationship.
- `Scope`: what the epic owns at behavior and contract level.
- `Development tasks`: child issues that implement the epic. Prefer GitHub sub-issues when available and keep issue links here as a readable fallback.
- `Decision needed`: optional note for committee/product/architecture decisions.
- `Acceptance criteria`: externally visible outcomes that prove the epic is done.
- `Out of scope`: explicit boundaries to avoid scope creep.
- `Risks and rollback`: delivery risks, operational risks, and recovery path if the plan is wrong.

## Development task fields

- `Parent epic`: required epic issue reference, for example `#123`.
- `Problem`: the specific problem this task solves.
- `Proposed approach`: current owner, reused logic, moved/deleted logic, contracts, data model, APIs, and edge cases.
- `Area`: primary ownership area.
- `Size`: rough reviewable implementation size from `XS` to `XL`.
- `Acceptance criteria`: observable completion checklist.
- `Tests and validation`: behavior tests, contract tests, manual checks, and commands.
- `Out of scope`: what this task deliberately does not change.

## Finding fields

- `Finding`: what was observed, where, and why it may matter.
- `Impact`: severity of the observation before triage.
- `Area`: primary ownership area.
- `Evidence`: links, logs, screenshots, customer report, or reproduction notes.
- `Proposed follow-up`: related epic/task or suggested next step.

## Epic ownership

Development tasks must belong to an epic.

Preferred relationship:

1. Create an epic issue with the Epic template.
2. Create development task issues with the Development task template.
3. Add each task as a GitHub sub-issue of the epic when available.
4. Keep the task body's `Parent epic` field as `#123`.

The `Parent epic` body field is intentionally duplicated with the GitHub relationship because it is stable for exports and automation. If the `Parent epic` section exists but is empty, the intake script must keep `needs:epic` even if another issue is mentioned elsewhere in the task.

## Findings

Findings are not treated as private by default. They remain in the canonical Eneo project with `kind:finding` and `needs:triage`.

When a finding becomes planned work:

1. Link it to an existing epic, or create a new epic.
2. Create one or more development tasks under that epic.
3. Keep the finding as evidence and context.

## Automation

`.github/workflows/add-to-project.yml` handles project intake:

- ensures planning labels exist;
- adds opened or reopened issues and PRs to project #5;
- labels structured issues by kind;
- marks development tasks with `needs:epic` if their `Parent epic` field does not reference an epic issue.

The workflow is non-blocking for PRs. It keeps project intake visible without making planning metadata a release gate. If this workflow is expanded later, keep privileged workflow code on the base branch and do not checkout/run PR head code in jobs that use `ADD_TO_PROJECT_PAT`.

When adding workflow inputs or untrusted issue/PR text to a `run:` step, pass the value through `env:` and reference the environment variable in shell. Do not interpolate GitHub contexts directly into shell commands in jobs that use `ADD_TO_PROJECT_PAT`. Checkout steps should keep `persist-credentials: false` unless the job must push back to the repository.

## Roadmap export

Export the roadmap graph locally:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --output roadmap.md
```

Export only Mermaid:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --format mermaid --output roadmap.mmd
```

Export a committee-oriented Markdown snapshot:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --audience committee --output committee-roadmap.md
```

Export a standup-oriented Markdown snapshot:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --audience standup --output standup-roadmap.md
```

Export a slide-like committee roadmap SVG:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --format svg --audience committee --output committee-roadmap.svg
```

Export with explicit columns, for example when a committee deck should always show empty future buckets:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --format svg --audience committee --versions 2.0,2.1,2.2,2.X --output committee-roadmap.svg
```

The `Export roadmap graph` workflow can also be run manually in GitHub Actions. It uploads the generated roadmap as an artifact and lets the runner choose `default`, `committee`, or `standup` audience.

## Validation

Run these checks after editing project workflow files:

```bash
node --check .github/scripts/project-intake.mjs
node --check .github/scripts/ensure-planning-labels.mjs
node --check scripts/export_github_roadmap.mjs
node .github/scripts/project-intake.mjs --self-test
node scripts/export_github_roadmap.mjs --self-test
```
