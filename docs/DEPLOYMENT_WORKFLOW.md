# Deployment Workflow

This document describes our Git workflow and deployment process. Please read it carefully before contributing.

## Table of Contents
- [Overview](#overview)
- [Environments](#environments)
- [Branch Strategy](#branch-strategy)
- [Development Workflow](#development-workflow)
- [Release Process](#release-process)
- [Release Stabilization (RC Process)](#release-stabilization-rc-process)
- [Hotfix Process](#hotfix-process)
- [Backporting](#backporting)
- [Security Patches Across Multiple Releases](#security-patches-across-multiple-releases)
- [Backflow: Release to Develop](#backflow-release-to-develop)
- [Support / Maintenance Policy](#support--maintenance-policy)
- [Docker Images](#docker-images)
- [Documentation Versions](#documentation-versions)
- [FAQ](#faq)

## Overview

We use a Git Flow-inspired workflow with **persistent release branches**. Every minor version gets a `release/v1.X` branch. Tags always live on release branches. Deployment systems consume a completed release bundle: the bundle attached to a tag's release, or for the development environment the bundle of the latest successful `develop` build. The `:develop` aliases are a convenience; they move one component at a time and can briefly mix revisions.

```mermaid
graph LR
    A[Feature Branch] -->|PR| B[develop]
    B -->|Push| C[Build :develop image]
    C -->|Image Update| D[Deploy to Dev]
    B -->|Create branch| E[release/v1.8]
    E -->|Tag v1.8.0-rc.1| F[Build :1.8.0-rc.1 image]
    F -->|Deploy| G[Test Environment]
    E -->|Tag v1.8.0| H[Build :1.8.0 image]
    H -->|Deploy| I[Production]
```

```
feature/* ──► develop ──► release/v1.8 ──► v1.8.0, v1.8.1, ...
                     ──► release/v1.9 ──► v1.9.0, ...

Backflow (patches):
  release/v1.X (hotfix) ──cherry-pick──► develop
```

## Environments

| Environment | Purpose | Branch/Tag | Image Tag | Deployment Method |
|------------|---------|------------|-----------|-------------------|
| **Development** | Latest features, may be unstable | `develop` | `develop` bundle (`:develop` alias) | Auto (on a completed bundle) |
| **Test** | Pre-production testing via RC tags | `v*-rc.*` tags on `release/v1.X` | `:1.8.0-rc.1` | Manual deploy |
| **Production** | Live system | `v*` tags on `release/v1.X` | `:1.8.0` | Manual deploy |

## Branch Strategy

### Long-lived Branches

#### `develop`
- Integration branch for new features
- Always deployable to dev environment
- Protected: accepts only pull requests that a member of `@eneo-ai/core-maintainers` adds to the merge queue, with all required checks green

#### `release/v1.X`
- Created from `develop` when ready to release or stabilize a minor version
- Persistent home for all patches to that minor version
- All version tags (`v1.X.Y`) live here
- Test via RC tags (`:1.8.0-rc.1`) before creating the final release
- **Never merged back** — fixes flow to `develop` via cherry-pick only
- Protected: only members of `@eneo-ai/core-maintainers` can create, update or delete release branches and create `v*` tags, so the release steps below require Core Maintainer access. Changes arrive through pull requests, and each needs an approval from a Core Maintainer other than its author. See [Governance and Roles](https://docs.eneo.ai/dev/contributing/governance)

### Supporting Branches

#### `feature/*`
- Created from: `develop`
- Merged into: `develop`
- Naming: `feature/descriptive-name`
- Example: `feature/add-user-authentication`

#### `hotfix/*`
- Created from: the target `release/v1.X` branch
- Merged into: the target `release/v1.X` branch (then cherry-picked to `develop`)
- Naming: `hotfix/issue-description`
- Example: `hotfix/fix-payment-processing`

## Development Workflow

### Step-by-Step Guide

#### 1. Start a New Feature

```bash
# Always start from latest develop
git checkout develop
git pull origin develop

# Create your feature branch
git checkout -b feature/your-feature-name

# Make your changes
git add .
git commit -m "feat: add new feature"

# Push to GitHub
git push origin feature/your-feature-name
```

#### 2. Create Pull Request

1. Go to GitHub and create a PR from your feature branch to `develop`
2. Fill in the PR template
3. Request review from team members
4. Address any feedback

#### 3. After PR Approval

Once merged to develop:
- GitHub Actions automatically builds Docker images tagged `:develop`
- Images are automatically deployed to internal dev environment

## Release Process

### Creating a Production Release

Every release goes through at least one RC tag for testing. See [Release Stabilization (RC Process)](#release-stabilization-rc-process) for the full flow.

Before tagging, make sure the user-facing release notes are on the release branch: `frontend/packages/whats-new/releases.json` must have an entry for the version with `date` set, reviewed by the release owner. The entry is drafted from the `## User-facing` sections of merged PRs — see [`frontend/packages/whats-new/PLAYBOOK.md`](../frontend/packages/whats-new/PLAYBOOK.md). It ships inside the frontend image as the in-app **What's new** page and is published on docs.eneo.ai; the GitHub release notes below remain the developer/operator-facing changelog.

Run the tag rule locally before creating the release, so a missing date is caught before a GitHub release exists whose image build then fails:

```bash
python3 scripts/check_whats_new.py --repo-root . --release-tag vX.Y.Z
```

Once the RC is stable, create the final release via GitHub UI:

1. Go to **Releases** → **Draft a new release**
2. Click **Choose a tag** → type `v1.8.0` → select **Create new tag**
3. Set **Target** to `release/v1.8`
4. Set **Release title** to `v1.8.0`
5. Write release notes (features, bug fixes, breaking changes)
6. Leave **Set as pre-release** unchecked
7. Click **Publish release**

GitHub Actions will automatically build the production images and complete the release bundle:
- `ghcr.io/eneo-ai/eneo-backend:1.8.0`
- `ghcr.io/eneo-ai/eneo-frontend:1.8.0`
- `ghcr.io/eneo-ai/eneo-web-next:1.8.0`
- `ghcr.io/eneo-ai/eneo-tool-runtime:1.8.0`

Deploy to production from the release bundle (`release.json` and `release.env` on the GitHub release), which records the exact image digests. An image tag can exist before its release has passed every check; the bundle is attached only after they pass.

### Semantic Versioning

We use semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR** (1.0.0 → 2.0.0): Breaking changes
- **MINOR** (1.0.0 → 1.1.0): New features (backwards compatible)
- **PATCH** (1.0.0 → 1.0.1): Bug fixes

## Release Stabilization (RC Process)

RC tags also live on the release branch. Create the release branch from `develop` when you're ready to **start** stabilizing:

```
develop ──► create release/v1.8
                 │
                 ├──► v1.8.0-rc.1 (tag, pre-release) → deploy to test env
                 ├──► fix via PR (a second Core Maintainer approves)
                 ├──► v1.8.0-rc.2 (tag, pre-release)
                 └──► v1.8.0 (final release)
```

**1. Create release branch from `develop`:**

```bash
git checkout develop && git pull
git checkout -b release/v1.8
git push origin release/v1.8
```

**2. Create the first RC via GitHub UI:**

1. Go to **Releases** → **Draft a new release**
2. Click **Choose a tag** → type `v1.8.0-rc.1` → select **Create new tag**
3. Set **Target** to `release/v1.8`
4. Set **Release title** to `v1.8.0-rc.1`
5. Check **Set as pre-release**
6. Click **Publish release**

**3. Fix issues** through `hotfix/*` pull requests into `release/v1.8`. Each one needs an approval from a Core Maintainer other than its author; direct pushes are rejected.

**4. Create subsequent RCs** the same way via GitHub Releases (tag `v1.8.0-rc.2`, target `release/v1.8`, mark as pre-release)

**5. When stable, create the final release** via GitHub Releases:
- Tag `v1.8.0`, target `release/v1.8`
- Leave **Set as pre-release** unchecked
- Add full release notes

During stabilization, `develop` can continue receiving new features for the next release.

## Hotfix Process

One consistent flow for all hotfixes, regardless of which version is affected:

```mermaid
flowchart TB
    A[Production Bug Found] --> B[Create hotfix from release/v1.X]
    B --> C[Fix Bug]
    C --> D[PR to release/v1.X]
    D --> D2[Second Core Maintainer approves]
    D2 --> E[Merge to release/v1.X]
    E --> F[Tag new patch version]
    F --> G[Build versioned image]
    G --> H[Deploy to Production]
    H --> I[Cherry-pick fix to develop]
```

### Hotfix Example

**1. Create hotfix from the affected release branch:**

```bash
git checkout release/v1.7
git pull origin release/v1.7
git checkout -b hotfix/fix-critical-bug

# Make your fix
git add .
git commit -m "fix: resolve critical payment processing error"

# Push and create PR to the release branch
git push origin hotfix/fix-critical-bug
gh pr create --base release/v1.7 --head hotfix/fix-critical-bug
```

Another Core Maintainer approves the pull request. Squash-merge it, so the fix is one commit on the release branch.

**2. After PR merge, create the patch release via GitHub UI:**

1. Go to **Releases** → **Draft a new release**
2. Click **Choose a tag** → type `v1.7.4` → select **Create new tag**
3. Set **Target** to `release/v1.7`
4. Set **Release title** to `v1.7.4`
5. Describe the fix in the release notes
6. Click **Publish release**

GitHub Actions builds the `1.7.4` images and the release bundle. The `:latest` tag is NOT overwritten if `v1.8.0` already exists.

**3. Deploy** `v1.7.4` to the affected production instance, using the image digests in its release bundle.

**4. Carry the fix to develop** with the procedure below.

## Carrying a Fix to Another Branch

Neither `develop` nor a release branch accepts direct pushes, so every cherry-pick goes through a pull request:

```bash
# 1. Find the commit the fix pull request landed (here PR #123)
SHA=$(gh pr view 123 --json mergeCommit --jq .mergeCommit.oid)
git fetch origin && git show --stat "$SHA"   # check that this is the whole fix

# 2. Apply it on a topic branch from the target branch
git checkout develop && git pull
git checkout -b fix/carry-xyz
git cherry-pick "$SHA"   # for a merge commit: git cherry-pick -m 1 "$SHA"
git push origin fix/carry-xyz

# 3. Open the pull request
gh pr create --base develop --head fix/carry-xyz
```

- **Source commit.** Take the commit from the fix's pull request, not the latest commit on the branch (another pull request may have landed since) and not the commits on your `hotfix/*` branch, which do not survive its deletion. Squash-merge fix pull requests so that this one commit is the whole fix. A rebase-merged pull request lands several commits; carry each of them, in order, or squash it instead.
- **Into `develop`.** The pull request needs the required checks and the merge queue; Core Maintainers agree on it together, with no formal approval.
- **Into a release branch.** Another Core Maintainer approves the pull request. Several fixes for the same release can go in one pull request.

## Backporting

When a bug is fixed on `develop` but also affects an older release, carry the fix to `release/v1.7` with the procedure above (base `release/v1.7`). After it lands on the release branch, tag via GitHub UI:

1. Go to **Releases** → **Draft a new release**
2. Tag: `v1.7.5`, Target: `release/v1.7`
3. Describe the backported fix
4. Click **Publish release**

## Security Patches Across Multiple Releases

When a security fix must go to multiple supported releases, follow [Fixing a Vulnerability](SECURITY.md#fixing-a-vulnerability): prepare the fixes privately, then open the public pull requests only when every line is ready, because the first one discloses the fix, and publish the patch releases and the advisory straight after.

1. **Fix on the oldest affected release branch first**
2. **Carry it forward** to each newer release branch, then to `develop`, with [the procedure above](#carrying-a-fix-to-another-branch)
3. **Tag new patch versions** on each affected release branch

Order matters: **oldest → newest → develop**. This minimizes merge conflicts since newer branches are closer to develop. Before each step, re-read the SHA of the commit the previous pull request landed on its branch.

**Example: security fix needed on v1.6, v1.7, and v1.8. Create releases for each branch via GitHub UI:**

| Tag | Target | Pre-release? |
|-----|--------|-------------|
| `v1.6.3` | `release/v1.6` | No |
| `v1.7.5` | `release/v1.7` | No |
| `v1.8.1` | `release/v1.8` | No |

For each: **Releases** → **Draft a new release** → set tag, target, and release notes → **Publish release**.

## Backflow: Release to Develop

**Every fix that lands on a release branch must also be cherry-picked to `develop`.** If you skip this, the fix will be missing in the next release.

After merging a hotfix PR to a release branch, **immediately** carry the fix to `develop` with [the procedure above](#carrying-a-fix-to-another-branch), using the commit on the release branch as the source.

This applies to all fixes on release branches — hotfixes, RC stabilization fixes, backported patches, and security fixes.

## Support / Maintenance Policy

Which release lines receive bug fixes and security patches is defined in [Supported Versions](SECURITY.md#supported-versions). Older release branches can be deleted after confirming that no deployment depends on them.

## Docker Images

### Image Tagging Strategy

| Source | Docker Tags | Purpose |
|--------|------------|---------|
| `develop` branch | `:develop`, `:develop-{sha}` | Development testing |
| `v*-rc/beta` tags | `:1.8.0-rc.1` (no `:latest`) | Test environment / pre-release testing |
| `v*` tags (stable) | `:1.8.0`, `:latest` (if highest version) | Production releases |

**How `:latest` is decided:** Evaluated at tag-push time by comparing the new tag against all existing stable tags (`v*` excluding pre-releases like `-rc`, `-beta`) via semver sort. Only the highest stable version wins `:latest`.

Consequences to be aware of:
- Patching an older release (e.g. tagging `v1.7.4` while `v1.8.0` exists) will NOT overwrite `:latest` — the older patch correctly stays out of `:latest`.
- If an out-of-order release happens (e.g. `v1.8.0` was tagged first, then later `v1.7.5` on the old branch), `:latest` still points to `v1.8.0` — the comparison is "highest at push time," not "most recently pushed."
- RC / pre-release tags never receive `:latest`, regardless of version number.
- If you ever need to move `:latest` to a different version (e.g. after yanking a bad release), you must retag manually in the registry — CI will not do it retroactively.

### Image Locations

```bash
# Backend Images
ghcr.io/eneo-ai/eneo-backend:develop      # Latest from develop
ghcr.io/eneo-ai/eneo-backend:1.8.0-rc.1  # RC for testing
ghcr.io/eneo-ai/eneo-backend:1.8.0       # Specific release
ghcr.io/eneo-ai/eneo-backend:latest       # Highest stable release

# Frontend Images
ghcr.io/eneo-ai/eneo-frontend:develop      # Latest from develop
ghcr.io/eneo-ai/eneo-frontend:1.8.0-rc.1  # RC for testing
ghcr.io/eneo-ai/eneo-frontend:1.8.0       # Specific release
ghcr.io/eneo-ai/eneo-frontend:latest       # Highest stable release
```

## Documentation Versions

[docs.eneo.ai](https://docs.eneo.ai) publishes stable, archived and development
documentation. Every release line has a `/vX.Y/` URL; `/dev/` follows develop,
and unversioned URLs redirect to the latest stable equivalent.

[The documentation authoring guide](../frontend/apps/docs-site/AUTHORING.md)
owns the rules for choosing a branch, page and release-note entry. Read it
before adding documentation or describing unreleased behaviour.
[The site README](../frontend/apps/docs-site/README.md) describes publication,
central triggers, retention and recovery. There is no manual version-folder
move at release time.

## FAQ

### Q: When should I create a feature branch?
**A:** For any change that adds functionality, fixes a bug, or modifies behavior. Even small changes should go through a PR for code review.

### Q: Can I push directly to develop or release branches?
**A:** No. `develop` only accepts pull requests through the merge queue, and release branches only accept pull requests that another Core Maintainer has approved. See [Carrying a Fix to Another Branch](#carrying-a-fix-to-another-branch) and [Governance and Roles](https://docs.eneo.ai/dev/contributing/governance).

### Q: Where and how do I create version tags?
**A:** Always on a `release/v1.X` branch. Use **GitHub Releases** (not the CLI) to create tags — this gives you release notes, pre-release marking, and a clean audit trail. See [Quick Command Reference](#creating-tags-github-ui).

### Q: How do I know what version to tag?
**A:** Check the latest tag on the repo's **Releases** page or with `git tag --list 'v*' --sort=-v:refname | head -1`. Then:
- Breaking changes → increment MAJOR
- New features → increment MINOR
- Bug fixes → increment PATCH

### Q: What if I need to patch an old version?
**A:** Use the same hotfix flow — create a `hotfix/*` branch from the relevant `release/v1.X`, PR to the release branch, get another Core Maintainer's approval, merge, tag. No special handling needed.

### Q: What if I need to test something quickly?
**A:** Create a feature branch and PR to develop. Once merged, it auto-deploys to dev environment.

### Q: Can I delete old feature branches?
**A:** Yes! Delete them after merging to keep the repo clean:
```bash
git push origin --delete feature/old-feature
git branch -d feature/old-feature
```

### Q: Can I delete old release branches?
**A:** Only if the version is EOL (see [Support / Maintenance Policy](#support--maintenance-policy)). Confirm no customers depend on that version first.

### Q: How do I rollback production?
**A:** Deploy the previous version tag:
```bash
# Check available versions
git tag --list 'v*' --sort=-v:refname

# Deploy previous version (e.g., v1.7.3 if v1.8.0 has issues)
# Use your deployment tool with v1.7.3 images
```

## Quick Command Reference

### Git commands

```bash
# Start new feature
git checkout develop && git pull
git checkout -b feature/my-feature

# Update feature branch with latest develop
git checkout feature/my-feature
git merge develop

# Create release branch
git checkout develop && git pull
git checkout -b release/v1.8
git push origin release/v1.8

# Hotfix any version
git checkout release/v1.7 && git pull
git checkout -b hotfix/critical-fix
# ... fix, push, PR to release/v1.7, second approval, merge ...
# Then tag via GitHub UI (see below)
# Carry the fix to develop through a PR (see "Carrying a Fix to Another Branch")
```

### Creating tags (GitHub UI)

Always create tags through **GitHub Releases** rather than the CLI. This gives you release notes, pre-release marking, and a consistent audit trail.

| Action | Tag | Target branch | Pre-release? |
|--------|-----|--------------|-------------|
| New release | `v1.8.0` | `release/v1.8` | No |
| Release candidate | `v1.8.0-rc.1` | `release/v1.8` | Yes |
| Hotfix patch | `v1.7.4` | `release/v1.7` | No |

**Steps:** Repo → **Releases** → **Draft a new release** → type new tag → select target branch → write notes → set pre-release if RC → **Publish release**

---
