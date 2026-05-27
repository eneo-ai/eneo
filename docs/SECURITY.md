# Security Policy

This policy explains how to report vulnerabilities in Eneo and how the
maintainers triage security work. Do not report sensitive vulnerabilities in
public GitHub issues, pull requests, or discussions.

## Reporting a Vulnerability

Email security reports to `security@sundsvall.se`.

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

Security fixes land on `develop` first. Supported release branches are any
release branches that are currently deployed or explicitly maintained by the
Eneo maintainers. Older tags and inactive branches are not guaranteed to receive
security fixes.

If a fix affects users outside the hosted/deployed environments, maintainers
should publish upgrade or mitigation guidance through a GitHub Security Advisory.

## Security Tooling

The repository uses GitHub security features and CI to prevent regressions:

- Dependabot creates weekly dependency update pull requests for backend,
  frontend, GitHub Actions, Dockerfiles, and devcontainer configuration.
- Dependency Review runs on pull requests into `develop` and blocks newly
  introduced vulnerable dependencies at `high` severity or above.
- CodeQL uses the repository's advanced GitHub Actions workflow so the scanned
  languages and query suites are versioned with the code. It scans Python,
  JavaScript/TypeScript, and GitHub Actions workflows on pushes and pull
  requests to `develop`, plus a weekly scheduled scan.
- Release SBOMs are generated from the published backend and frontend container
  image digests and attached to GitHub Releases as CycloneDX JSON, SPDX JSON,
  and human-readable table files. These assets provide dependency transparency
  for each release; their authenticity currently relies on GitHub-managed
  release asset storage and the image digests recorded in the SBOM bundle.
  `SBOM-SHA256SUMS.txt` covers the SBOM files; container image integrity is
  verified through the GHCR image digests recorded in `IMAGE-DIGESTS.txt`.
- Secret scanning and push protection should remain enabled for provider keys,
  tokens, credentials, and other repository secrets.
- The normal `CI` gate validates frozen backend and frontend installs before
  dependency update pull requests are merged.

During the initial rollout, branch protection should require `CI`, `Dependency
Review`, and `CodeQL`, but CodeQL code-scanning protection should only block
high and critical alerts. Do not block every medium or low finding until the
baseline is stable.

## Alert Triage

Use this order for existing Dependabot, malware, secret scanning, Dependency
Review, Docker, GitHub Actions, and CodeQL alerts.

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
3. Prefer the Dependabot security PR. If Dependabot cannot create one, manually
   bump, pin, replace, or remove the dependency.
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
- use the Dependabot security PR if GitHub has an advisory
- manually bump, pin, or temporarily remove the package if no advisory exists yet
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

## Developer Expectations

- Use frozen installs for dependency changes.
- Do not bypass security gates without a documented exception.
- Keep dependency PRs small enough to review.
- Read changelogs for packages that handle prompts, credentials, networking,
  file parsing, authentication, authorization, or deployment.
- Prefer patch and minor updates first while the alert backlog is being reduced.
- Revisit the Dependency Review threshold after the critical and high backlog is
  stable.
