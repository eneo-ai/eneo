# Security Policy

This policy explains how to report vulnerabilities in Eneo and how the
maintainers triage security work. Do not report sensitive vulnerabilities in
public GitHub issues, pull requests, or discussions.

## Reporting a Vulnerability

Report a vulnerability privately. GitHub is the preferred way:

- **Preferred: on GitHub**, through **Security → Report a vulnerability**
  (<https://github.com/eneo-ai/eneo/security/advisories/new>). The report is
  visible only to you, the maintainers and anyone they invite to help, and the
  fix is coordinated with you in the same private advisory.
- **If you cannot use GitHub**, by email to `security@sundsvall.se`.

Include as much of the following as possible:

- affected version, commit, branch, or deployment environment
- affected component, endpoint, package, workflow, or Docker image
- impact and the data, tenant, credential, or permission boundary involved
- reproduction steps or a minimal proof of concept
- relevant logs, screenshots, request IDs, or dependency/advisory links
- whether the issue is already public or under active exploitation
- suggested remediation, if known
- contact details for coordinated follow-up

Please do not publicly disclose the issue until a fix or mitigation is
available and maintainers have had a reasonable coordination window.

## What Happens After You Report

1. **Triage.** A report made through GitHub opens a private security advisory
   that only you, the maintainers and anyone they invite can see. A Core
   Maintainer aims to respond within the first-response targets below. Triage
   decides whether the report is accepted or closed with an explanation, for
   example when it is out of scope or a duplicate. For an e-mail report, the
   maintainers can open a private advisory and add you to it if you have a
   GitHub account.
2. **Fix.** The maintainers rate the severity and prepare a fix or mitigation
   for the affected supported release lines. The conversation stays in the
   advisory, where you can follow the work and check the fix.
3. **Publish.** When the fix has landed and the patch releases are out, the
   advisory is published as soon as practical. It names the affected and
   patched versions and credits you as the reporter, unless you ask not to be
   named.

## Scope

In scope:

- the code in this repository and the container images Eneo publishes
  (`ghcr.io/eneo-ai/eneo-*`)
- the build, release and publication workflows in `.github/`
- the reference deployment configuration in `docs/deployment/`

Out of scope here:

- a vulnerability in a specific organisation's Eneo deployment that comes from
  how it is hosted or configured: report it to that organisation
- a vulnerability in a third-party dependency that is already public: open an
  ordinary issue or pull request so the dependency can be updated
- findings without a security impact, such as an outdated software version
  without a reachable vulnerability

When in doubt, report it privately; the maintainers will tell you where it
belongs.

## Testing Guidelines

- Test against your own local or test installation, never against a
  deployment you do not operate.
- Use your own accounts and test data. Do not access, change or keep data that
  belongs to other users or tenants; if you reach it by accident, stop and say
  so in the report.
- Do not degrade the service: no denial-of-service, load or spam tests.
- Stop at the smallest proof of concept that shows the impact.
- Keep the details private until the advisory is published.

## Response Targets

These are targets, not guarantees. Active exploitation, exposed secrets, malware,
or vulnerabilities affecting authentication, authorization, file parsing, prompt
handling, LLM provider credentials, SSRF, RCE, or deserialization take priority.

| Severity | First response | Initial triage | Target fix or mitigation |
| --- | --- | --- | --- |
| Critical | 1 business day | 1 business day | As soon as practical |
| High | 1 business day | 2 business days | 30 days |
| Medium | 2 business days | 5 business days | 90 days |
| Low | 5 business days | Next maintenance cycle | Best effort |

## Supported Versions

Supported release branches are any release branches that are currently deployed
or explicitly maintained by the Eneo maintainers. Older tags and inactive
branches are not guaranteed to receive security fixes. This section is the
canonical support policy; other guides link here.

## Fixing a Vulnerability

Our policy is to prepare a fix or mitigation for `develop` and each affected
supported `release/vX.Y` branch, and to record any delayed fix or accepted risk
under [Tracking and Exceptions](#tracking-and-exceptions). How the fix is
prepared depends on whether the vulnerability is already public.

- **Reported privately.** Keep the work private until it is ready. Confirm and
  rate the report in a private GitHub Security Advisory, and prepare and review
  the fix for every affected line in the advisory's temporary private fork or
  on unpublished local branches. Then land it the normal way: ordinary pull
  requests into `develop` (required checks and merge queue) and into each
  release branch (second Core Maintainer approval), followed by the patch
  releases and the advisory, naming the affected and patched versions. The
  first public pull request discloses the fix, so open them only when every
  line is ready, and keep the time from the first public pull request to the
  published advisory as short as the checks allow. Do not use the advisory's
  **Merge** button: it merges into `develop` without status checks, rulesets
  or the merge queue.
- **Already public**, such as a published advisory for a dependency. Fix it in
  ordinary pull requests on `develop` and backport it to the supported release
  lines.

Publish upgrade or mitigation guidance through a GitHub Security Advisory
whenever operators need to act.

## Security Tooling

The repository uses GitHub security features and CI to prevent regressions:

- Dependabot alerts are enabled. Dependabot version updates are configured for
  backend, frontend, GitHub Actions, Dockerfiles, and devcontainer
  configuration, but paused (`open-pull-requests-limit: 0`). Dependabot
  security updates are off, so maintainers triage alerts and patch vulnerable
  dependencies in focused `fix(deps)` pull requests. The tool runtime
  (`tool-runtime/`) has no Dependabot entry.
- Dependency Review runs on pull requests into `develop` and blocks newly
  introduced vulnerable dependencies at `high` severity or above.
- The self-hosted [Review Agent](https://github.com/CCimen/review-agent) gives
  a second opinion from another AI model on security and code quality when a
  maintainer comments `/review` on a pull request. It reads the exact commits
  through bounded read tools and tries to disprove each candidate finding
  before reporting it; findings can still be wrong. It has no write access or
  merge authority, does not gate the merge and is not a full security audit
  ([how reviews work](https://ccimen.github.io/review-agent/docs/how-reviews-work)). Our rule is to fix or answer its findings before
  merging.
- The reusable `Security` workflow audits the complete runtime Python lock and
  frontend lock, runs Semgrep security-audit/GitHub Actions rules over
  `backend/src`, both frontends' sources and `.github`, and scans the added Git
  history with Gitleaks. It runs inside CI on pull requests into `develop` and
  `release/**` and on merge-queue candidates, and weekly on a schedule. CI is a
  required check only on `develop`; on release branches it runs but does not
  block the merge, and pull requests into `main` do not run it.
  On `develop` and tag builds, component images are pushed while the checks
  run; only the completed release bundle waits for them, so deployments must
  consume the bundle. The tool runtime's `bun.lock` is not part of the audit.
  Reports are retained as CI artifacts.
- Temporary dependency mitigations belong in `frontend/patches/SECURITY.md`, with
  an owner, exact advisory, regression tests and review expiry. The audit retains
  the raw finding and only accepts the named mitigation after its tests pass.
- Gitleaks exclusions in `.gitleaks.toml` require both an exact file path and
  an exact reviewed test credential or generated schema example. They apply
  only to the named rule, survive squash commits and line moves, and do not
  exclude entire files, directories or rules. The security workflow tests that
  changed values and values outside their reviewed files are still detected.
  The scan covers newly added history only. Revoke or rotate any real
  credential that is found; a scan cannot prove that a credential was revoked.
- CodeQL advanced setup is paused while maintainers evaluate a code-scanning
  setup that gives developers useful feedback without high false-positive noise.
  Re-enable code scanning only after the query set and triage process are tuned
  enough that alerts are actionable for maintainers.
- Release SBOMs are generated from the published backend, Svelte frontend, Next
  frontend, tool runtime, and bundled SeaweedFS container image digests and
  attached to GitHub Releases as CycloneDX JSON, SPDX JSON,
  and human-readable table files. The backend release also includes a narrower
  CycloneDX SBOM for the Python runtime installed in `/app/.venv` inside the
  released backend image. The frontend release also includes a source dependency
  SBOM generated with CycloneDX Generator after installing the frontend from the
  checked-out release tag with the frozen Bun lockfile, so JavaScript
  dependencies remain visible even when the runtime image only contains the
  bundled build output. Release SBOM assets are attested through GitHub artifact
  attestations, and the pushed backend, frontend, web-next, tool runtime, and
  SeaweedFS images include provenance attestations in GHCR. Fixable HIGH and
  CRITICAL image vulnerabilities block the frontend, web-next, and tool runtime
  images; the backend image has no image scan and relies on the audit of
  its Python lock.
  `SBOM-SHA256SUMS.txt` covers the SBOM files; `IMAGE-DIGESTS.txt` labels the
  exact image digests scanned by platform and records the bundled store's
  multi-platform manifest reference for deployment.
- The bundled object store is an Eneo-built artifact, not an upstream-signed
  SeaweedFS image. `.github/workflows/seaweedfs_image.yml` owns it and runs
  only when its pinned inputs change, so application image publishing is never
  blocked by object-store policy drift. Privileged build, attestation, and
  publication jobs run only for `develop` and use the GitHub OIDC workflow
  identity—no PAT, registry password, or signing key. Pull requests and manual
  runs from other branches run the same source policy, build, smoke test, SBOM,
  and vulnerability gate against an ephemeral local registry with read-only
  permissions; nothing reaches GHCR and nothing is attested. The workflow pins the SeaweedFS 4.40 source commit/archive, Dockerfile
  frontend, compiler image, runtime image, tools, and every Action by immutable
  digest or full commit SHA. A hashed downstream patch upgrades dependencies
  with known advisories until upstream includes those fixes. It publishes only
  after both Linux platform candidates pass source/license policy, a
  reproducibility rebuild, the exact reference Compose bootstrap and
  persistence smoke, a reachable Go vulnerability scan, and a Grype gate that
  includes unfixed HIGH/CRITICAL findings.
- The published tag is `ghcr.io/eneo-ai/eneo-seaweedfs:<docker/seaweedfs/VERSION>`
  and is immutable by policy: the serialized publish job refuses to move a
  version tag to different content and fails closed when it cannot read the
  registry. An identical rebuild leaves the tag untouched and emits fresh
  attestations bound to its own source commit. Every change to the image
  inputs bumps `VERSION`.
  A weekly scheduled run re-audits the pinned source and both published
  platform digests against current Go and Grype vulnerability databases
  without rebuilding or publishing; a red scheduled run is the signal to bump
  the downstream patch (see `docker/seaweedfs/README.md`).
- SeaweedFS source-license classifier gaps are resolved only by exact
  module/version/license-file hashes in `docker/seaweedfs/verify-supply-chain.sh`.
  Any dependency, version, license content, or unknown-package drift fails the
  job for review. This is not a general allowlist or vulnerability waiver.
- The `object-content-supply-chain` GitHub Environment is the protected
  trusted-publication boundary, with a deployment branch policy that allows
  only `develop`; the workflow enforces the same rule in code, and the
  environment policy is the backstop. No pull-request workflow publishes
  images. Fork pull requests get a read-only token; the tool runtime image job
  still requests package write, OIDC, and attestation permissions on
  same-repository pull requests although it publishes only when the
  coordinator calls it. Do not make the
  path-filtered SeaweedFS workflow a required status check. The canonical
  image/SBOM owners remain `.github/workflows/build_and_push_images.yml`,
  `.github/workflows/seaweedfs_image.yml`, and
  `.github/workflows/release_sbom.yml`; do not create a parallel signing system.
- Secret scanning and push protection are enabled for provider keys, tokens,
  credentials, and other repository secrets. Keep them enabled.
- The normal `CI` gate validates frozen backend and frontend installs before
  dependency update pull requests are merged.

The `develop` ruleset requires `CI` and `Dependency Review`, and the PR label
classification ruleset requires `PR labels` on `develop`, `main` and
`release/**`. No ruleset requires a CodeQL check while code scanning is paused.

## Repository Access and Change Control

Access to the `eneo-ai` organisation follows least privilege. Core Maintainers
(the Eneo team at Sundsvalls kommun) steward the platform and are accountable
for what is merged and released. Collaborators from partner municipalities and
agencies contribute through pull requests. The contributor-facing explanation,
including the role table, diagrams and an FAQ, is
[Governance and Roles](https://docs.eneo.ai/dev/contributing/governance)
on the documentation site.

- **Roles.** `@eneo-ai/core-maintainers` is the only team with write-level
  (Maintain) access. It also holds the organisation's Security manager role.
  Collaborators (`@eneo-ai/collaborators`) and individual outside
  collaborators have Triage access and contribute from forks. A small number of organisation owners hold
  Admin rights for rulesets, team access and repository settings. The
  organisation base permission is read.
- **`develop`.** Changes arrive only through pull requests, and only people
  with write access (the Core Maintainers and the organisation owners) can add
  a pull request to the merge queue; the Core Maintainers do the ordinary
  merges. Required checks must
  pass and review conversations must be resolved. A Core Maintainer reviews
  and approves contributions from outside the team before queueing them;
  `.github/CODEOWNERS` requests that review automatically. If someone without
  write access pushes new commits afterwards, GitHub cancels the pending
  merge. Core Maintainers agree on their own changes as a team and may queue
  them without a formal approval.
- **Releases.** Only Core Maintainers can create, update or delete
  `release/**` branches and `v*` tags. A `v*` tag starts image publication,
  so this restriction controls who can publish a release. Every pull request
  into a release branch needs an approval from a Core Maintainer other than its
  author: the `Release and main review` ruleset requires one approval and
  code-owner review, has no bypass actors, and dismisses an approval when new
  commits are pushed. Each release branch therefore needs `.github/CODEOWNERS`.
- **`main`.** The same review rule applies, and `main` is protected against
  deletion and force pushes.
- **No bypass on `develop`.** The `develop` ruleset has no bypass actors, so
  no ordinary pull request can skip the required checks or the merge queue.
  Merging from a security advisory's private fork would skip them, so our
  procedure is not to use it. Repository
  administrators are not exempt from rulesets unless they are on a bypass
  list. If GitHub itself blocks a critical fix, an organisation owner may
  change the ruleset temporarily; restore it straight away and record the
  change in a GitHub issue. The release branch and tag rulesets keep Core
  Maintainers as bypass actors because cutting releases requires it.
- **Workflow trust.** Pull requests from forks run with a read-only
  `GITHUB_TOKEN` and without repository secrets. Workflows started from
  branches in this repository can request package write permissions, which is
  why write access stays with the Core Maintainers and the organisation owners. Keep repository
  and organisation secrets limited to those referenced by workflows; when a
  secret is no longer used, delete it and revoke it at its source.
- **Changes to access.** Only organisation owners change team roles, rulesets
  or bypass lists. Record each change in a GitHub issue so the access history
  is reviewable.

## Alert Triage

Use this order for existing Dependabot, malware, secret scanning, Dependency
Review, Docker, GitHub Actions, and any enabled code-scanning alerts.

### P0: Same Day

- Dependabot malware alerts
- secret scanning alerts
- critical runtime vulnerabilities
- issues affecting authentication, authorization, file parsing, prompt or LLM
  provider credentials, SSRF, RCE, or deserialization

For Eneo, treat packages such as LiteLLM, LangChain, MCP clients/servers, HTTP
clients, cryptography libraries, FastAPI, document parsing libraries, frontend
frameworks, and build tooling as higher risk because they process prompts,
files, network calls, credentials, or user-controlled content.

### P1: 48-72 Hours

- high severity runtime vulnerabilities
- vulnerable Docker base images used in production
- vulnerable GitHub Actions used in trusted workflows

### P2: 1-2 Weeks

- medium runtime vulnerabilities
- critical or high dev-only vulnerabilities that execute during build or test

### P3: Monthly

- low severity alerts
- dev-only issues with no practical exploit path
- major version update backlog

Do not dismiss alerts just to reduce the count. Dismiss only with a clear reason
such as "vulnerable code not used", "false positive", or "tolerable risk", and
record an expiry date or follow-up issue.

## New Alert Workflow

For each new alert:

1. Classify it as malware, secret exposure, runtime dependency, dev dependency,
   Docker image, GitHub Action, or code scanning.
2. Check whether it is reachable in Eneo and whether it touches user input,
   files, prompts, credentials, authentication, network calls, or deployment.
3. Bump, pin, replace, or remove the dependency in a focused `fix(deps)` pull
   request, and backport it to the supported release lines that ship it.
4. Review the diff. For AI and LLM packages, check changelogs for telemetry,
   callback behavior, environment variable handling, proxy behavior, logging
   changes, and changed defaults.
5. Run frozen-lockfile installs, CI, and any relevant smoke tests.
6. Merge only after the relevant checks pass or an explicit risk exception is
   documented.
7. Verify the alert closes. If it does not, inspect lockfiles for remaining
   vulnerable transitive dependencies.
8. If the issue cannot be fixed immediately, create a GitHub issue or security
   tracking item with owner, risk, mitigation, and target date.

## LLM Provider Package Incidents

Treat incidents in packages that handle LLM provider keys, prompts, proxying,
model routing, callbacks, or request logging as higher severity than ordinary
library updates.

Immediate response:

- check whether Eneo uses the affected package and version
- bump, pin, or temporarily remove the package, whether or not an advisory
  exists yet
- rotate any potentially exposed provider keys
- review application logs, CI artifacts, Sentry events, build logs, and package
  install logs
- publish a GitHub Security Advisory if users need to upgrade or take action
- add a regression or security test when the incident involved logging,
  credential handling, SSRF, authentication bypass, or unsafe defaults

Dependabot is useful once an advisory exists, but it is not a replacement for
incident response when the ecosystem learns about a compromise before the GitHub
Advisory Database is updated.

## Secrets

Use GitHub Actions secrets for CI and deployment credentials. Use Dependabot
secrets only when Dependabot needs access to a private package registry. Do not
store runtime application secrets in Dependabot secrets.

If a secret is exposed:

- revoke or rotate it
- inspect logs and artifacts for use or exfiltration
- remove it from repository history if needed
- add or adjust secret scanning patterns when the secret format is specific to
  Eneo

## Log Redaction

Eneo's structured-log path enforces redaction on both stdout log attributes and auto-instrumented span attributes:

- `Authorization`, `Cookie`, and `Set-Cookie` headers are never logged.
- Query parameters named `code`, `state`, `token`, `access_token`, `refresh_token`, `client_secret`, or matching `*token*` or `*secret*` (case-insensitive) are replaced with `[REDACTED]` in both log lines and span URL attributes.
- Request and response bodies are not logged by default; adding body logging requires a deliberate code change and a redaction review.
- `user_email` is logged as a deliberate carryover from existing audit behavior. It is high-cardinality PII; configure the log aggregation system not to pre-index it.

The redaction policy is unit-tested across both layers (stdout logs and span attributes from FastAPI, `httpx`, and `aiohttp` instrumentation). For the full policy and verification commands, see [OBSERVABILITY.md §8](./OBSERVABILITY.md#8-redaction-policy).

## Tracking and Exceptions

Track security work in GitHub issues or GitHub Security Advisories, not in
private chat threads. Use labels such as `security`, `dependencies`,
`backend`, `frontend`, `docker`, and `github-actions` so maintainers can filter
the backlog. Add unresolved security issues to the Eneo project board and set
the Security status when the item needs team visibility.

Each accepted risk or delayed fix needs:

- owner
- affected component
- reason for delay
- mitigation
- target date
- review date or expiry condition

Object-content image policy has no standing exceptions. A future CVE or license
exception must name the exact advisory/license and artifact digest, owner,
reason, compensating control, and expiry. Absent that human-approved record, the
publication fails closed.

## Developer Expectations

- Use frozen installs for dependency changes.
- Do not bypass security gates without a documented exception.
- Keep dependency PRs small enough to review.
- Read changelogs for packages that handle prompts, credentials, networking,
  file parsing, authentication, authorization, or deployment.
- Prefer patch and minor updates first while the alert backlog is being reduced.
- Revisit the Dependency Review threshold after the critical and high backlog is
  stable.
