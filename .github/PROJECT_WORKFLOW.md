# Eneo project workflow

Eneo uses one canonical organization project for product planning:

- Project: https://github.com/orgs/eneo-ai/projects/5
- Owner: `eneo-ai`
- Purpose: roadmap, active development, findings, and review intake in one place

Older projects can remain as historical references while open work is moved into the canonical project.

## Item kinds

Use one item kind per issue:

- `Epic`: roadmap-level outcome, planned by version, owns development tasks.
- `Task`: buildable development item, must belong to an epic.
- `Bug`: reported product defect. Triage decides whether it becomes planned task work.
- `Finding`: observed issue, risk, or improvement candidate. Findings can stay in the main project.
- `Chore`: maintenance work without direct product behavior.

The project should keep a `Kind` single-select field. The desired options are:

- `Epic`
- `Task`
- `Bug`
- `Finding`
- `Chore`

If GitHub does not allow adding `Finding` to the existing field through automation, add it manually in the project settings.

## Versioned roadmap

Epics carry a `Roadmap version` value in the issue body, for example `2.1`, `2.2`, `2.3`, `Future`, or `Unscheduled`.

The project can also have a `Roadmap version` single-select field with the same options. The issue body remains the fallback source so roadmap exports keep working even if the field has not been configured yet.

Recommended roadmap views:

- `Roadmap`: layout Roadmap, filter `kind:epic` or `Kind:Epic`, grouped by roadmap version.
- `Epics`: table, filter `kind:epic` or `Kind:Epic`.
- `Active work`: table or board, filter out `status:Done`.
- `Findings`: table, filter `kind:finding` or `Kind:Finding`.
- `Needs triage`: table, filter `label:needs:triage`.
- `Needs epic`: table, filter `label:needs:epic`.

## Adding new items

Most new planning work should start manually from the GitHub issue chooser:

1. Open a new issue in `eneo-ai/eneo`.
2. Choose `Epic`, `Development task`, `Finding`, `Bug Report`, or `Feature Request`.
3. Fill in the required fields.
4. Submit the issue. The template and intake workflow add it to the canonical Eneo project.

Use `Epic` when the idea belongs on the roadmap and may contain several implementation tasks. This is the preferred starting point for product planning such as "comes in 2.1" or "comes in 2.2".

Use `Development task` when the work is already scoped enough to build. A task should reference an epic in `Parent epic`, for example `#123`.

Use `Finding` when something has been observed but is not yet planned. A finding can later be converted into one or more tasks under an epic.

AI-assisted development should follow the same model:

1. If AI discovers a follow-up during implementation, create or suggest a `Finding` unless the work is already clearly scoped.
2. If AI is asked to plan new roadmap work, create or suggest an `Epic`.
3. If AI is asked to split an approved epic, create `Development task` issues and link each one to the epic.
4. AI-created tasks must include the parent epic reference in the issue body so automation and exports can resolve the relationship.

Do not create disconnected tasks for roadmap work. If there is no suitable epic, create the epic first and then add tasks under it.

## Epic fields

The Epic template fields have these meanings:

- `Summary`: short non-technical description of the outcome and why it matters.
- `Roadmap version`: planned release bucket such as `2.1`, `2.2`, `2.3`, `Future`, or `Unscheduled`.
- `Priority`: relative order inside the roadmap version. `P0` is urgent or release-critical; `P3` is lowest priority.
- `Area`: primary ownership area: `Backend`, `Frontend`, `Infra`, `Docs`, `Security`, or `Other`.
- `Flow / architecture`: optional Mermaid graph for the main user flow or system relationship.
- `Scope`: what the epic owns at behavior and contract level.
- `Development tasks`: child issues that implement the epic. Prefer GitHub sub-issues when available and keep issue links here as a readable fallback.
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

The `Parent epic` body field is intentionally duplicated with the GitHub relationship because it is stable for exports and automation.

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

The workflow is non-blocking for PRs. It keeps project intake visible without making planning metadata a release gate.

## Roadmap export

Export the roadmap graph locally:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --output roadmap.md
```

Export only Mermaid:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --format mermaid --output roadmap.mmd
```

The `Export roadmap graph` workflow can also be run manually in GitHub Actions. It uploads the generated roadmap as an artifact.
