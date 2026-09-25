#!/usr/bin/env node
// Derives the documentation versions to publish from git refs, so nothing has to
// be edited at release time:
//
//   stable   the release/vX.Y branch tip (or the tag itself) of the highest final
//            vX.Y.Z tag — hotfixes to docs on the release branch republish stable
//   archive  the next DOCS_ARCHIVED_LINES older release lines, served under /vX.Y
//   dev      the working tree (develop on deploys, the PR head on pull requests)
//
// Release candidates (v2.2.0-rc.1) never count as final, so stable does not flip
// until the real tag exists. A release line is skipped when its ref has no
// docs-site content. When no final tag with docs exists, the root links to /dev/. Every version has a permanent base path.
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const APP_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
export const WORKTREE_REF = "WORKTREE";
export const REPO_CONTENT_DIR = "frontend/apps/docs-site/src/content";

const FINAL_TAG = /^v(\d+)\.(\d+)\.(\d+)$/;

// git resolves tree paths relative to the cwd, so every call runs from the repo root.
export const REPO_ROOT = execFileSync("git", ["rev-parse", "--show-toplevel"], {
  cwd: APP_DIR,
  encoding: "utf8",
}).trim();

function git(repoRoot, ...args) {
  return execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" }).trim();
}

function refExists(repoRoot, ref) {
  try {
    execFileSync(
      "git",
      ["rev-parse", "--verify", "--quiet", `${ref}^{commit}`],
      {
        cwd: repoRoot,
        stdio: "ignore",
      },
    );
    return true;
  } catch {
    return false;
  }
}

function hasDocsContent(repoRoot, ref) {
  try {
    return (
      git(repoRoot, "ls-tree", "-d", ref, "--", REPO_CONTENT_DIR).length > 0
    );
  } catch {
    return false;
  }
}

function parseTag(name) {
  const match = FINAL_TAG.exec(name);
  if (!match) return null;
  const [major, minor, patch] = match.slice(1).map(Number);
  return { name, major, minor, patch };
}

function newestFirst(a, b) {
  return b.major - a.major || b.minor - a.minor || b.patch - a.patch;
}

function releaseLines(repoRoot) {
  const tags = git(repoRoot, "tag", "-l", "v*")
    .split("\n")
    .map(parseTag)
    .filter(Boolean)
    .sort(newestFirst);
  const lines = new Map();
  for (const tag of tags) {
    const line = `v${tag.major}.${tag.minor}`;
    if (!lines.has(line)) lines.set(line, tag);
  }
  return [...lines].map(([line, tag]) => {
    const branch = [`origin/release/${line}`, `release/${line}`].find((ref) =>
      refExists(repoRoot, ref),
    );
    return { line, tag: tag.name, ref: branch ?? tag.name };
  });
}

export function resolveVersions({
  archivedLines = Number(process.env.DOCS_ARCHIVED_LINES ?? 3),
  only,
  repoRoot = REPO_ROOT,
} = {}) {
  if (
    !Number.isInteger(archivedLines) ||
    archivedLines < 0 ||
    archivedLines > 20
  )
    throw new Error("archivedLines must be an integer between 0 and 20");
  if (only !== undefined && only !== "dev")
    throw new Error("--only accepts dev");
  const dev = {
    id: "dev",
    label: "dev",
    kind: "dev",
    ref: WORKTREE_REF,
    gitRef: process.env.DOCS_DEV_GIT_REF || "develop",
    basePath: "/dev",
  };
  if (only === "dev") return [{ ...dev, basePath: "" }];

  const versions = releaseLines(repoRoot)
    .filter((line) => hasDocsContent(repoRoot, line.ref))
    .slice(0, archivedLines + 1)
    .map((line, index) => ({
      id: line.line,
      label: line.line,
      kind: index === 0 ? "stable" : "archive",
      ref: git(repoRoot, "rev-parse", `${line.ref}^{commit}`),
      gitRef: line.ref.replace(/^origin\//, ""),
      tag: line.tag,
      basePath: `/${line.line}`,
    }));

  versions.push(dev);
  return versions;
}

// Git tree ids make scheduled reconciliation cheap: code-only changes outside
// the documentation inputs do not trigger another multi-version build.
export function sourceDigest(repoRoot, versions) {
  const inputs = [
    "frontend/apps/docs-site",
    "frontend/packages/whats-new",
    "frontend/bun.lock",
    "frontend/package.json",
    ".github/workflows/deploy_docs.yml",
  ];
  const trees = inputs.map((file) =>
    git(repoRoot, "ls-tree", "HEAD", "--", file),
  );
  return createHash("sha256")
    .update(JSON.stringify({ versions, trees }))
    .digest("hex");
}

export function parseArgs(argv) {
  const args = { only: undefined, out: undefined, archivedLines: undefined };
  for (let i = 0; i < argv.length; i++) {
    if (
      ["--only", "--out", "--archived"].includes(argv[i]) &&
      (!argv[i + 1] || argv[i + 1].startsWith("--"))
    )
      throw new Error(`Missing value for ${argv[i]}`);
    switch (argv[i]) {
      case "--only":
        args.only = argv[++i];
        break;
      case "--out":
        args.out = argv[++i];
        break;
      case "--archived":
        args.archivedLines = Number(argv[++i]);
        break;
      default:
        throw new Error(`Unknown argument: ${argv[i]}`);
    }
  }
  return args;
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const args = parseArgs(process.argv.slice(2));
  const versions = resolveVersions(args);
  const json = JSON.stringify(
    { sourceDigest: sourceDigest(REPO_ROOT, versions), versions },
    null,
    2,
  );
  if (args.out) writeFileSync(args.out, json + "\n");
  else console.log(json);
}
