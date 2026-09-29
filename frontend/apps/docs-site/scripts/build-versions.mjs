#!/usr/bin/env node
// Build in disposable directories. Source files and the last complete site are
// never removed to start a build; publish only after every version succeeds.
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  APP_DIR,
  REPO_ROOT,
  WORKTREE_REF,
  parseArgs,
  resolveVersions,
  sourceDigest,
} from "./resolve-versions.mjs";

const APP_PATH = "frontend/apps/docs-site";
const NOTES_PATH = "frontend/packages/whats-new";
const excluded = new Set(["node_modules", ".next", "out", "site", ".git"]);

function copySource(source, target) {
  const include = (entry) =>
    !path
      .relative(source, entry)
      .split(path.sep)
      .some(
        (part) =>
          excluded.has(part) ||
          part.startsWith(".docs-build-") ||
          part.startsWith(".env"),
      );
  fs.mkdirSync(target, { recursive: true });
  // Copy children, not the containing app: the disposable directory is on the
  // same filesystem as site/ so the final publication can use atomic renames.
  for (const name of fs.readdirSync(source)) {
    const entry = path.join(source, name);
    if (include(entry))
      fs.cpSync(entry, path.join(target, name), {
        recursive: true,
        filter: include,
      });
  }
}

function existsAt(repoRoot, ref, file) {
  return (
    execFileSync("git", ["ls-tree", ref, "--", file], {
      cwd: repoRoot,
      encoding: "utf8",
    }).trim() !== ""
  );
}

function extract(repoRoot, ref, paths, target) {
  const archive = path.join(target, "snapshot.tar");
  execFileSync("git", ["archive", "-o", archive, ref, "--", ...paths], {
    cwd: repoRoot,
  });
  execFileSync("tar", ["-xf", archive, "-C", target]);
  fs.rmSync(archive);
}

// Link installed third-party dependencies without copying their contents.
// The workspace release package is linked to the isolated snapshot instead.
function linkDependencies(source, target, releasePackage) {
  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source)) {
    if (entry === "@eneo" && releasePackage) {
      fs.mkdirSync(path.join(target, entry));
      for (const name of fs.readdirSync(path.join(source, entry))) {
        if (name !== "whats-new")
          fs.symlinkSync(
            fs.realpathSync(path.join(source, entry, name)),
            path.join(target, entry, name),
            "dir",
          );
      }
    } else {
      fs.symlinkSync(
        fs.realpathSync(path.join(source, entry)),
        path.join(target, entry),
        "dir",
      );
    }
  }
  if (releasePackage) {
    fs.mkdirSync(path.join(target, "@eneo"), { recursive: true });
    fs.symlinkSync(releasePackage, path.join(target, "@eneo/whats-new"), "dir");
  }
}

function prepareVersion({ appDir, repoRoot, version, workspace }) {
  const app = path.join(workspace, "app");
  copySource(appDir, app);
  const packageSource = path.join(repoRoot, NOTES_PATH);
  const releasePackage = fs.existsSync(packageSource)
    ? path.join(workspace, "whats-new")
    : undefined;
  if (releasePackage) copySource(packageSource, releasePackage);
  if (version.ref !== WORKTREE_REF) {
    const snapshot = path.join(workspace, "snapshot");
    fs.mkdirSync(snapshot);
    const paths = [`${APP_PATH}/src/content`, `${APP_PATH}/public`];
    const notes = `${NOTES_PATH}/releases.json`;
    const hasNotes = existsAt(repoRoot, version.ref, notes);
    if (hasNotes) paths.push(notes);
    extract(repoRoot, version.ref, paths, snapshot);
    for (const directory of ["src/content", "public"]) {
      fs.rmSync(path.join(app, directory), { recursive: true, force: true });
      fs.cpSync(
        path.join(snapshot, APP_PATH, directory),
        path.join(app, directory),
        { recursive: true },
      );
    }
    if (releasePackage) {
      // Release lines predating What's new have no notes. Never substitute dev's.
      const destination = path.join(releasePackage, "releases.json");
      if (hasNotes) fs.copyFileSync(path.join(snapshot, notes), destination);
      else fs.writeFileSync(destination, JSON.stringify({ releases: [] }));
    }
  }
  const misplaced = fs
    .readdirSync(path.join(app, "src/content"))
    .find((name) => /^v\d+\.\d+$/.test(name));
  if (misplaced)
    throw new Error(
      `Do not author version folders in src/content/${misplaced}; choose the release branch (see AUTHORING.md)`,
    );
  linkDependencies(
    path.join(appDir, "node_modules"),
    path.join(app, "node_modules"),
    releasePackage,
  );
  return app;
}

async function runBuild(app, env, signal) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.env.BUN_BIN || "bun", ["run", "build"], {
      cwd: app,
      env,
      stdio: "inherit",
      signal,
    });
    let error;
    child.on("error", (cause) => {
      error = cause;
    });
    child.on("close", (code) =>
      error
        ? reject(error)
        : code === 0
          ? resolve()
          : reject(new Error(`docs build exited with status ${code}`)),
    );
  });
}

function redirectPage(target) {
  // Targets come from version ids and URL-encoded exported paths.
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex"><meta http-equiv="refresh" content="0;url=${target}"><link rel="canonical" href="${target}"><title>Eneo documentation</title></head><body><a href="${target}">Open documentation</a><script>location.replace(${JSON.stringify(target)} + location.search + location.hash)</script></body></html>`;
}

function addLatestLinks(site, version) {
  const root = path.join(site, version.basePath.slice(1));
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith("_")) visit(file);
        continue;
      }
      if (!entry.name.endsWith(".html")) continue;
      const relative = path.relative(root, file);
      if (relative === "404.html") {
        fs.copyFileSync(file, path.join(site, "404.html"));
        continue;
      }
      const route = relative
        .split(path.sep)
        .map(encodeURIComponent)
        .join("/")
        .replace(/(?:^|\/)index\.html$/, "")
        .replace(/\.html$/, "");
      const target = `${version.basePath}/${route}`;
      const alias = path.join(site, relative);
      fs.mkdirSync(path.dirname(alias), { recursive: true });
      fs.writeFileSync(alias, redirectPage(target));
    }
  }
  visit(root);
}

export async function buildSite({
  appDir = APP_DIR,
  repoRoot = REPO_ROOT,
  versions,
  digest,
  build = runBuild,
  signal = new AbortController().signal,
}) {
  const workspace = fs.mkdtempSync(path.join(appDir, ".docs-build-"));
  const pending = path.join(workspace, "site");
  const destination = path.join(appDir, "site");
  const previous = path.join(workspace, "previous-site");
  fs.mkdirSync(pending);
  let preserveRecovery = false;
  try {
    for (const version of versions) {
      signal.throwIfAborted();
      const directory = path.join(workspace, version.id);
      fs.mkdirSync(directory);
      const app = prepareVersion({
        appDir,
        repoRoot,
        version,
        workspace: directory,
      });
      const env = {
        ...process.env,
        PAGES_BASE_PATH: version.basePath,
        NEXT_PUBLIC_DOCS_VERSION: version.id,
        NEXT_PUBLIC_DOCS_VERSIONS: JSON.stringify(versions),
        NEXT_PUBLIC_DOCS_REF: version.gitRef,
      };
      console.log(
        `Building ${version.id} from ${version.ref} at ${version.basePath || "/"}`,
      );
      await build(app, env, signal);
      signal.throwIfAborted();
      fs.cpSync(
        path.join(app, "out"),
        path.join(pending, version.basePath.slice(1)),
        { recursive: true },
      );
      fs.rmSync(directory, { recursive: true });
    }
    const latest = versions.find((v) => v.kind === "stable") ?? versions[0];
    if (latest.basePath) addLatestLinks(pending, latest);
    const cname = path.join(appDir, "public/CNAME");
    if (fs.existsSync(cname))
      fs.copyFileSync(cname, path.join(pending, "CNAME"));
    fs.writeFileSync(
      path.join(pending, "versions.json"),
      JSON.stringify({ sourceDigest: digest, versions }, null, 2) + "\n",
    );
    signal.throwIfAborted();
    if (fs.existsSync(destination)) fs.renameSync(destination, previous);
    try {
      fs.renameSync(pending, destination);
    } catch (error) {
      if (fs.existsSync(previous)) {
        try {
          fs.renameSync(previous, destination);
        } catch (recoveryError) {
          preserveRecovery = true;
          throw new AggregateError(
            [error, recoveryError],
            `Previous publication retained at ${previous}`,
          );
        }
      }
      throw error;
    }
  } finally {
    if (!preserveRecovery)
      fs.rmSync(workspace, { recursive: true, force: true });
  }
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const controller = new AbortController();
  const stop = () =>
    controller.abort(new Error("Documentation build interrupted"));
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    const versions = resolveVersions(parseArgs(process.argv.slice(2)));
    await buildSite({
      versions,
      digest: sourceDigest(REPO_ROOT, versions),
      signal: controller.signal,
    });
  } finally {
    process.removeListener("SIGINT", stop);
    process.removeListener("SIGTERM", stop);
  }
}
