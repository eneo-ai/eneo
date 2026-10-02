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
- Pull requests must carry explicit change-type and area labels before merge. Missing planning links remain visible without blocking delivery.

## Canonical metadata model

Use one source of truth for humans and keep fallback metadata only for automation/export:

- Human UI/source of truth: GitHub issue type, Parent issue/sub-issues, GitHub Project fields, and GitHub Project views.
- Automation/export fallback: `kind:*` labels and issue body sections.

Project `Kind` is the human-facing field for project views and draft items. `kind:*` labels remain the issue-template default and automation/export fallback. Keep them aligned where practical, and do not add another kind-like field.

## Item kinds

Use one item kind per issue:

- `Epic`: roadmap-level outcome, planned by version, owns development tasks.
- `Task`: buildable development item, must belong to an epic.
- `Bug`: reported product defect. Triage decides whether it becomes planned task work.
- `Finding`: observed issue, risk, or improvement candidate. Findings can stay in the main project.
- `Chore`: maintenance work without direct product behavior.

Use native GitHub issue types where available. GitHub includes default `task`, `bug`, and `feature` issue types at the organization level. Custom types such as `Epic`, `Finding`, or `Initiative` can be added later if the organization wants them, but the current workflow does not require them.

## Required labels

Labels describe delivered work for filtering and reporting. The executable
catalog and validation rules live in `.github/scripts/label-policy.mjs`.
`ensure-labels.mjs` creates or updates that catalog without deleting other labels.
Do not add synonymous labels such as `fix`, `feature`, or a second `chore`.

### Pull requests

Apply exactly one primary change type, based on the intent of the final diff:

| Label | Meaning |
| --- | --- |
| `bug` | Correct existing behavior that does not meet its intended contract. |
| `enhancement` | Introduce or improve product behavior. |
| `dependencies` | Update dependencies, including runtime or container versions. |
| `refactor` | Restructure code without an intended behavior change. |
| `kind:chore` | Maintenance, tooling, or test-only work without direct product behavior. |

Use `documentation` alone for documentation-only work. When documentation
accompanies one of the primary types above, keep both labels; `documentation`
then describes the documentation area and does not create a second primary type.
A bug fix with matching tests and docs is still `bug`, not `bug` plus `kind:chore`.
Split unrelated changes instead of assigning conflicting primary types.

Also apply at least one affected area:
`backend`, `frontend`, `infra`, `documentation`, `ci`, `github-actions`, `docker`,
`devcontainer`, or `security`. Several areas can apply. `security` also serves as
a cross-cutting signal; add the concrete subsystem when known.

Additional signals do not replace a primary type:

- `security`: security-sensitive behavior or vulnerability work.
- `accessibility`: accessibility barriers or WCAG conformance work.
- `breaking-change`: consumers or operators must adapt when upgrading. Explain
  the required adaptation in the PR and the appropriate upgrade documentation.
- `python:uv`: identifies the dependency ecosystem; pair it with `backend` or
  another actual area.

Examples:

| Work | Labels |
| --- | --- |
| API bug fix with matching documentation | `bug`, `backend`, `documentation` |
| Frontend restructuring | `refactor`, `frontend` |
| Keyboard interaction fix | `bug`, `frontend`, `accessibility` |
| Container dependency update | `dependencies`, `docker` |
| CI maintenance | `kind:chore`, `ci` |
| Documentation-only correction | `documentation` |

Apply real GitHub labels through the sidebar or CLI, for example:

```bash
gh pr edit 123 --repo eneo-ai/eneo --add-label bug --add-label backend
```

Label names written in a PR body do not count. The **PR labels** check reads the
current labels every time it runs, including manual reruns. It reruns after
label changes, new commits, reopening, editing, and entering the merge queue.
It validates all PRs in a merge-group candidate again. Drafts can remain
unclassified while being written, but their check stays red until classified.
Bots and backports have no exemption; Dependabot's configured labels already
meet the policy. `needs:*`, `kind:task`, `kind:epic`, and `kind:finding` do not
classify a PR's change type.

### Issues and planning

Issue kind answers what is being planned: epic, task, finding, bug, feature,
or chore. It is distinct from the change type of each implementing PR. Keep the
native issue type, Project `Kind`, and `kind:*` mirrors aligned. Do not put
`kind:chore` on a `kind:task` issue merely because an implementing PR is maintenance.

All issue forms require an explicit `Area` selection, with no preselected
`Other`. Intake maps Backend, Frontend, Infra, Docs, and Security to their
corresponding labels. Editing that selection removes the previous form area and
adds the new one; unrelated labels are retained. Epic and task forms no longer
claim that every item is an `enhancement`.

`Other`, missing classification, and issues created outside the forms are kept
visible with `needs:triage` when their kind/type or area is missing. Maintainers
must classify those issues before treating them as ready. Issue creation through
the API cannot be blocked by a PR status check. Completing labels does not remove
`needs:triage` automatically: it may also represent outstanding human review.

Project `Status`, `Priority`, and `Roadmap version` remain the planning owners.
The existing `priority:P0` through `priority:P3` labels describe security response
priority; they are not a second general-purpose planning priority.

### Enforcement and recovery

`pr-labels.yml` uses trusted default-branch code on `pull_request_target` so the
same policy covers older release branches. It has read-only permissions and
never executes a PR's code. `merge_group` runs the same trusted policy.
Repository/organization Actions event policies must allow this metadata-only
`pull_request_target` workflow; blocking that event also blocks the required check.

Roll out in this order:

1. Merge the workflow, catalog, tests, forms, and agent instructions into `develop`.
2. Run `node .github/scripts/ensure-labels.mjs` with a token that can manage labels.
3. Verify that **PR labels** reports success on a correctly labeled PR and fails
   after removing a required label. Verify a merge-group candidate as well.
4. Require **PR labels** from the GitHub Actions app in an active branch ruleset
   for `develop`, `main`, and `release/**`. Preserve other required checks and
   protections. Exempt branch creation so a release branch can be cut normally.

Do not require a check before its workflow is available. If rollout causes a
workflow failure, remove only the **PR labels** requirement from its dedicated
ruleset while fixing the workflow; keep CI and dependency checks in force.

### Reporting

Use the policy's primary change type for mutually exclusive change counts;
area and signal totals overlap. Keep issues, epics, and PRs as separate measures.
Report PRs to `develop` separately from backports to release branches, using the
target branch rather than another manually maintained label.
Labels are mutable. Historical relabeling needs review and does not recreate the
classification at merge time; use retained snapshots/events for that requirement.

## Versioned roadmap

Epics carry a `Roadmap version` value in the issue body and/or Project field, for example `2.1`, `2.2`, `2.3`, `2.X`, `Future`, or `Unscheduled`.

`Roadmap version` is a release bucket for grouping, filtering, and export. It is not the timeline field for GitHub's Roadmap layout.

Use the version string that is useful for planning. Adding `2.2` or `2.2 RC` should not require a code change; update the issue or Project field value. Project #5 should keep `Roadmap version` as a text field so new version buckets do not require Project option maintenance. The issue body remains a free-form export fallback.

GitHub Releases and release-candidate tags are delivery artifacts, not the source of truth for roadmap planning. Use release names such as `2.2 RC` in `Roadmap version` only when the roadmap needs that planning bucket.

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
- `Needs task link`: table, filter `label:needs:task-link`.
- `Done since last committee`: table, filter epics/tasks done since the last committee meeting date.

## Required GitHub setup

Configure this once after merge:

- Organization project: `eneo-ai/5`.
- Secret: `ADD_TO_PROJECT_PAT`.
- Token access: enough to read/update organization Project #5 fields and items, plus read repo issues/PRs used by the export and intake workflows.
- Required issue types: `task`, `bug`, `feature`.
- Optional custom issue types later: `Epic`, `Finding`, `Initiative`.
- Required Project fields: `Kind`, `Status`, `Roadmap version`, `Start date`, `Target date`, `Priority`, `Area`, `Owner / lead`, `Sponsor / municipality`, `Decision needed`.
- Enable hidden Project fields: `Parent issue`, `Sub-issue progress`.
- Recommended views: `Committee Roadmap`, `Standup`, `Epics`, `Active work`, `Findings`, `Needs triage`, `Needs epic`, `Needs task link`, `Done since last committee`.

Issue forms also list `projects: ["eneo-ai/5"]` for convenience. If the issue creator lacks write access to the org project, the intake workflow and Project auto-add should still add the item.

The workflows run `.github/scripts/ensure-project-fields.mjs` after validating `ADD_TO_PROJECT_PAT`. The script creates missing planning fields and adds missing standard options for `Status`, `Area`, `Priority`, and `Kind`. It does not delete team-specific options or change Project view layouts.

Run the setup script manually after changing Project #5 fields:

```bash
GH_TOKEN=... node .github/scripts/ensure-project-fields.mjs
```

Run a local script check without touching GitHub:

```bash
node .github/scripts/ensure-project-fields.mjs --self-test
```

### `ADD_TO_PROJECT_PAT` setup

`ADD_TO_PROJECT_PAT` must be an Actions secret, not an Actions variable. Variables are visible as plain configuration and must not contain tokens.

Use a fine-grained personal access token when possible:

- Resource owner: `eneo-ai`.
- Repository access: `eneo-ai/eneo`.
- Organization permission: Projects read/write.
- Repository permissions: Issues read-only and Pull requests read-only.
- Expiration: set a real expiry date and rotate the secret before it expires.

If using a classic personal access token instead, use the narrowest token that can still access organization Projects and this repository. The local `gh` setup used for verification had `repo`, `read:org`, `project`, and `workflow` scopes; the `workflow` scope is only needed for local workflow inspection, not for the Actions secret itself.

Create the repository secret in GitHub:

1. Open `eneo-ai/eneo` -> `Settings`.
2. Open `Secrets and variables` -> `Actions`.
3. Stay on the `Secrets` tab.
4. Click `New repository secret`.
5. Name: `ADD_TO_PROJECT_PAT`.
6. Secret: paste the token value.
7. Save, then rerun `Export roadmap graph`.

You can also set it with GitHub CLI:

```bash
gh secret set ADD_TO_PROJECT_PAT --repo eneo-ai/eneo
```

The CLI prompts for the token value. Do not put the token in chat, commit it, or store it as a repository variable.

## Adding new items

Most new planning work should start manually from the GitHub issue chooser:

1. Open a new issue in `eneo-ai/eneo`.
2. Choose `Epic`, `Development task`, `Finding`, `Bug Report`, or `Feature Request`.
3. Fill in the required fields.
4. Submit the issue. The template and intake workflow add it to the canonical Eneo project.

Use `Epic` when the idea belongs on the roadmap and may contain several implementation tasks. This is the preferred starting point for product planning such as "comes in 2.1" or "comes in 2.2".

Use `Development task` when the work is already scoped enough to build. A task should reference an epic in `Parent epic`, for example `#123`; intake then adds the task as a sub-issue of that epic. The sub-issue relationship is the parent link that GitHub and Project #5 use.

Open pull requests against development tasks, not epics. Link the task with `Fixes #123` in the PR body or under **Development** in the PR sidebar; both close the task when the PR merges into `develop`. A bug issue can be linked the same way. The task owns the parent epic relationship.

Use `Finding` when something has been observed but is not yet planned. A finding can later be converted into one or more tasks under an epic.

Use a Project draft item for an initiative that belongs to Eneo as a whole but does not yet belong to a repo. Convert it to an issue once implementation needs tracking in a repo.

AI-assisted development should follow the same model:

1. If AI discovers a follow-up during implementation, create or suggest a `Finding` unless the work is already clearly scoped.
2. If AI is asked to plan new roadmap work, create or suggest an `Epic`.
3. If AI is asked to split an approved epic, create `Development task` issues and link each one to the epic.
4. AI-created tasks must include the parent epic reference in the `Parent epic` field so intake can create the sub-issue relationship.
5. AI-created PRs must link the development task with a closing reference such as `Fixes #123`.

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
3. Fill in the task's `Parent epic` field as `#123`.

The GitHub sub-issue relationship is the parent link. Intake creates it from the `Parent epic` field when the task has no parent yet, provided the field holds exactly one `#123` or issue URL in this repository and that issue is an epic. It never replaces an existing parent. Tasks without a parent keep `needs:epic`, even if another issue is mentioned elsewhere in the task.

Pull requests should close the task issue, not the epic. This keeps the roadmap at outcome level and the code review at implementation level.

## Findings

Findings are not treated as private by default. They remain in the canonical Eneo project with `kind:finding` and `needs:triage`.

When a finding becomes planned work:

1. Link it to an existing epic, or create a new epic.
2. Create one or more development tasks under that epic.
3. Keep the finding as evidence and context.

## Automation

`.github/workflows/add-to-project.yml` handles project intake:

- ensures the classification and planning labels exist;
- adds opened or reopened issues and PRs to project #5;
- labels structured issues by kind and their selected area, and marks incomplete classification for triage;
- adds a development task as a sub-issue of the epic named in its `Parent epic` field, and marks it `needs:epic` while it has no parent epic;
- marks ready PRs into `develop` with `needs:task-link` while GitHub reports no issue they close. PRs into release or feature branches are not checked, because the PR into `develop` carries the link.

Intake re-reads the current issue or PR on every run. Linking in a sidebar triggers no workflow, so the label updates on the next edit or label change; removing the label refreshes it immediately.

Planning links remain non-blocking; classification is enforced separately by
**PR labels**. Issue classification runs before Project token validation, so a
missing `ADD_TO_PROJECT_PAT` cannot prevent labeling. Keep privileged workflow
code on the trusted default branch and do not checkout/run PR head code in jobs
that use `ADD_TO_PROJECT_PAT`.

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

Export the public website data contract:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs \
  --owner eneo-ai \
  --project 5 \
  --repository eneo-ai/eneo \
  --format json \
  --audience default \
  --output roadmap.json
```

JSON is always a public projection. It includes only real issue epics whose
Project payload has `content.type: Issue` and the exact repository
`eneo-ai/eneo`; Project draft items and issues from other repositories are
excluded. Public item fields are an explicit allowlist. Adding a Project field
or an internal exporter field never adds it to public JSON automatically.

Schema version 1 exposes these item fields:

- `number`, `url`, `title`, and the complete Epic `Summary`;
- Project `status`, `roadmapVersion`, `area`, `priority`, `sponsor`,
  `startDate`, and `targetDate`;
- `group`: `in_progress`, `next`, `later`, or `delivered`.

The envelope also exposes `unpublishedItemCount`. It counts epic-level Project
items that are not public `eneo-ai/eneo` issues. A non-zero value is a
transparency gap: convert the item to a public epic issue or reclassify it if it
does not belong on the roadmap. The export still succeeds so the public page
does not become stale, but consumers should surface or alert on the count.

`Done` items are delivered. Active or blocked items are in progress. `Todo`
items in the earliest concrete numeric release family among public `Todo` items
are next; remaining items are later. The raw status and roadmap version remain
in the projection so the website can change presentation without reparsing
Project data.

Export with explicit columns, for example when a committee deck should always show empty future buckets:

```bash
GH_TOKEN=... node scripts/export_github_roadmap.mjs --owner eneo-ai --project 5 --format svg --audience committee --versions 2.0,2.1,2.2,2.X --output committee-roadmap.svg
```

The `Export roadmap graph` workflow can also be run manually in GitHub Actions. It uploads the generated roadmap as an artifact and lets the runner choose `default`, `committee`, or `standup` audience.

The same workflow runs every six hours and uploads the public JSON projection
as the stable artifact `eneo-roadmap-public-json` with 30-day retention.
Scheduled exports are read-only and do not run the Project field setup script.
Manual Markdown, Mermaid, and SVG artifacts can contain Project-only planning
metadata, are not public website inputs, and have one-day retention.

### Website automation handoff

The website workflow should download the latest successful scheduled
`eneo-roadmap-public-json` artifact, translate and cache only changed item
content, then commit its own rendered data only when that downstream data
changes.

GitHub's automatic `GITHUB_TOKEN` is scoped to the repository where the
workflow runs. A workflow in `eneo-ai-website` therefore needs a fine-grained
token stored there as `ROADMAP_ARTIFACT_TOKEN` with read-only Actions access to
`eneo-ai/eneo`. It does not need organization Project access when it consumes
the artifact. Keep `ANTHROPIC_API_KEY` only in the website repository for the
translation step.

A shell-based consumer can resolve and download the artifact with:

```bash
run_id="$(
  GH_TOKEN="$ROADMAP_ARTIFACT_TOKEN" gh run list \
    --repo eneo-ai/eneo \
    --workflow export-roadmap.yml \
    --event schedule \
    --status success \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId'
)"

GH_TOKEN="$ROADMAP_ARTIFACT_TOKEN" gh run download "$run_id" \
  --repo eneo-ai/eneo \
  --name eneo-roadmap-public-json \
  --dir data/roadmap-source
```

The website should retain its last committed roadmap if source download,
schema validation, or translation fails. Pin `schemaVersion: 1`, reject unknown
schema versions, and hash item `title` plus `summary` for translation caching;
do not include the envelope `generatedAt` in that cache key. Alert or visibly
flag a non-zero `unpublishedItemCount` instead of silently presenting the feed
as complete.

If an epic appears under `Unscheduled`, set its `Roadmap version` Project field or fill in the `Roadmap version` section in the epic issue body. The export does not use GitHub Releases, tags, or milestones as the roadmap source of truth.

## Validation

Run these checks after editing project workflow files:

```bash
node --check .github/scripts/ensure-project-fields.mjs
node --check .github/scripts/project-intake.mjs
node --check .github/scripts/ensure-labels.mjs
node --check .github/scripts/check-pr-labels.mjs
node --test --test-concurrency=1 .github/scripts/label-policy.test.mjs
node --check scripts/export_github_roadmap.mjs
node .github/scripts/ensure-project-fields.mjs --self-test
node .github/scripts/project-intake.mjs --self-test
node scripts/export_github_roadmap.mjs --self-test
```
