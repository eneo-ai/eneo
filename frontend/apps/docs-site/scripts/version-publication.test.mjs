import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { test } from "node:test";
import { buildSite } from "./build-versions.mjs";
import {
  resolveVersions,
  parseArgs,
  sourceDigest,
} from "./resolve-versions.mjs";

function fixture(t) {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-docs-test-"));
  t.after(() => fs.rmSync(repoRoot, { recursive: true, force: true }));
  const appDir = path.join(repoRoot, "frontend/apps/docs-site");
  const packageDir = path.join(repoRoot, "frontend/packages/whats-new");
  function write(file, content) {
    const target = path.join(repoRoot, file);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
  const git = (...args) =>
    execFileSync(
      "git",
      ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", ...args],
      {
        cwd: repoRoot,
        env: {
          ...process.env,
          GIT_CONFIG_NOSYSTEM: "1",
          GIT_CONFIG_GLOBAL: "/dev/null",
        },
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    ).trim();
  git("init", "-b", "develop");
  git("config", "user.name", "Docs test");
  git("config", "user.email", "docs-test@example.invalid");
  write(".gitignore", "node_modules/\nsite/\n.docs-build-*/\n");
  write("frontend/apps/docs-site/src/content/index.mdx", "Released docs");
  write("frontend/apps/docs-site/public/CNAME", "docs.eneo.ai");
  write("frontend/apps/docs-site/src/app/layout.tsx", "Current renderer");
  write(
    "frontend/packages/whats-new/package.json",
    JSON.stringify({
      name: "@eneo/whats-new",
      exports: { "./releases.json": "./releases.json" },
    }),
  );
  write(
    "frontend/packages/whats-new/releases.json",
    JSON.stringify({
      releases: [{ version: "2.1.0", date: "2026-01-01", entries: [] }],
    }),
  );
  git("add", ".");
  git("commit", "-m", "Release docs");
  git("tag", "v2.1.0");
  git("branch", "release/v2.1");
  write(
    "frontend/apps/docs-site/src/content/index.mdx",
    "Uncommitted development docs",
  );
  write(
    "frontend/packages/whats-new/releases.json",
    JSON.stringify({ releases: [{ version: "3.0.0", entries: [] }] }),
  );
  fs.mkdirSync(path.join(appDir, "node_modules/@eneo"), { recursive: true });
  fs.symlinkSync(
    packageDir,
    path.join(appDir, "node_modules/@eneo/whats-new"),
    "dir",
  );
  fs.mkdirSync(path.join(appDir, "site"));
  fs.writeFileSync(
    path.join(appDir, "site/previous.html"),
    "last complete publication",
  );
  return { repoRoot, appDir, packageDir, git, write };
}

function exportPages(app) {
  fs.mkdirSync(path.join(app, "out/guides"), { recursive: true });
  fs.writeFileSync(path.join(app, "out/index.html"), "home");
  fs.writeFileSync(path.join(app, "out/guides/deployment.html"), "guide");
  fs.writeFileSync(path.join(app, "out/404.html"), "missing page");
}

function assertUntouched(f) {
  assert.equal(
    fs.readFileSync(path.join(f.appDir, "src/content/index.mdx"), "utf8"),
    "Uncommitted development docs",
  );
  assert.equal(
    fs.readFileSync(path.join(f.appDir, "site/previous.html"), "utf8"),
    "last complete publication",
  );
  assert.equal(
    fs.readdirSync(f.appDir).some((name) => name.startsWith(".docs-build-")),
    false,
  );
}

test("final tags select a release line, ignore RCs and pin content to a commit", (t) => {
  const f = fixture(t);
  f.git("tag", "v9.0.0-rc.1");
  const versions = resolveVersions({ repoRoot: f.repoRoot });
  assert.equal(versions.length, 2);
  assert.deepEqual(
    versions.map((v) => [v.id, v.basePath]),
    [
      ["v2.1", "/v2.1"],
      ["dev", "/dev"],
    ],
  );
  assert.equal(versions[0].ref, f.git("rev-parse", "release/v2.1"));
  assert.equal(versions[0].gitRef, "release/v2.1");
});

test("the permanent URL survives promotion to an archive", (t) => {
  const f = fixture(t);
  const previous = resolveVersions({ repoRoot: f.repoRoot })[0];
  f.git("tag", "v2.2.0");
  const versions = resolveVersions({ repoRoot: f.repoRoot });
  assert.equal(versions[0].id, "v2.2");
  assert.equal(versions[1].kind, "archive");
  assert.equal(versions[1].basePath, previous.basePath);
});

test("release branch fixes are selected without another release tag", (t) => {
  const f = fixture(t);
  f.git("add", ".");
  f.git("commit", "-m", "Documentation correction");
  f.git("branch", "-f", "release/v2.1", "HEAD");
  assert.equal(
    resolveVersions({ repoRoot: f.repoRoot })[0].ref,
    f.git("rev-parse", "HEAD"),
  );
});

test("a removed release branch falls back to its tag", (t) => {
  const f = fixture(t);
  f.git("branch", "-D", "release/v2.1");
  assert.equal(resolveVersions({ repoRoot: f.repoRoot })[0].gitRef, "v2.1.0");
});

test("repositories without final releases retain the permanent dev URL", (t) => {
  const f = fixture(t);
  f.git("tag", "-d", "v2.1.0");
  assert.deepEqual(
    resolveVersions({ repoRoot: f.repoRoot }).map((v) => v.basePath),
    ["/dev"],
  );
});

test("archive count and command arguments are validated", (t) => {
  const f = fixture(t);
  for (const archivedLines of [-1, 1.5, NaN, 21])
    assert.throws(() =>
      resolveVersions({ repoRoot: f.repoRoot, archivedLines }),
    );
  assert.throws(() =>
    resolveVersions({ repoRoot: f.repoRoot, only: "stable" }),
  );
  assert.throws(() => parseArgs(["--strict"]));
  assert.equal(
    resolveVersions({ repoRoot: f.repoRoot, only: "dev" })[0].basePath,
    "",
  );
});

test("successful publication combines current renderer with each ref’s docs and notes", async (t) => {
  const f = fixture(t);
  const versions = resolveVersions({ repoRoot: f.repoRoot });
  const observed = [];
  await buildSite({
    ...f,
    versions,
    digest: "test-digest",
    build: async (app, env) => {
      const require = createRequire(path.join(app, "package.json"));
      const notes = JSON.parse(
        fs.readFileSync(
          require.resolve("@eneo/whats-new/releases.json"),
          "utf8",
        ),
      );
      observed.push([
        env.NEXT_PUBLIC_DOCS_VERSION,
        notes.releases[0].version,
        fs.readFileSync(path.join(app, "src/content/index.mdx"), "utf8"),
      ]);
      assert.equal(
        fs.readFileSync(path.join(app, "src/app/layout.tsx"), "utf8"),
        "Current renderer",
      );
      assert.equal(JSON.parse(env.NEXT_PUBLIC_DOCS_VERSIONS).length, 2);
      exportPages(app);
    },
  });
  assert.deepEqual(observed, [
    ["v2.1", "2.1.0", "Released docs"],
    ["dev", "3.0.0", "Uncommitted development docs"],
  ]);
  const site = path.join(f.appDir, "site");
  assert.equal(
    fs.readFileSync(path.join(site, "v2.1/guides/deployment.html"), "utf8"),
    "guide",
  );
  assert.match(
    fs.readFileSync(path.join(site, "guides/deployment.html"), "utf8"),
    /\/v2.1\/guides\/deployment/,
  );
  assert.match(
    fs.readFileSync(path.join(site, "index.html"), "utf8"),
    /location.search \+ location.hash/,
  );
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(site, "versions.json"), "utf8"))
      .sourceDigest,
    "test-digest",
  );
  assert.equal(fs.existsSync(path.join(site, "previous.html")), false);
  assert.equal(
    fs.readFileSync(path.join(f.appDir, "src/content/index.mdx"), "utf8"),
    "Uncommitted development docs",
  );
});

for (const failure of ["stable", "archive", "dev"])
  test(`${failure} failure preserves source files and the entire previous publication`, async (t) => {
    const f = fixture(t);
    f.git("tag", "v2.2.0");
    const versions = resolveVersions({ repoRoot: f.repoRoot });
    await assert.rejects(
      buildSite({
        ...f,
        versions,
        build: async (app, env) => {
          const current = versions.find(
            (v) => v.id === env.NEXT_PUBLIC_DOCS_VERSION,
          );
          if (current.kind === failure) throw new Error("Invalid MDX");
          exportPages(app);
        },
      }),
      /Invalid MDX/,
    );
    assertUntouched(f);
  });

test("missing content extraction preserves sources and can be retried safely", async (t) => {
  const f = fixture(t);
  f.git("rm", "-r", "--cached", "frontend/apps/docs-site/public");
  f.git("commit", "-m", "No public directory");
  const versions = resolveVersions({ repoRoot: f.repoRoot });
  versions[0].ref = f.git("rev-parse", "HEAD");
  for (let attempt = 0; attempt < 2; attempt++) {
    await assert.rejects(
      buildSite({
        ...f,
        versions,
        build: async () => assert.fail("must not build missing content"),
      }),
    );
    assertUntouched(f);
  }
});

test("cancellation during a build preserves source files and the published site", async (t) => {
  const f = fixture(t);
  const controller = new AbortController();
  await assert.rejects(
    buildSite({
      ...f,
      versions: resolveVersions({ repoRoot: f.repoRoot }),
      signal: controller.signal,
      build: async (app) => {
        exportPages(app);
        controller.abort(new Error("cancelled"));
      },
    }),
    /cancelled/,
  );
  assertUntouched(f);
});

test("release lines predating What’s new receive empty notes rather than dev notes", async (t) => {
  const f = fixture(t);
  f.git("rm", "--cached", "frontend/packages/whats-new/releases.json");
  f.git("commit", "-m", "Before release notes existed");
  f.git("branch", "-f", "release/v2.1", "HEAD");
  await buildSite({
    ...f,
    versions: resolveVersions({ repoRoot: f.repoRoot }),
    build: async (app, env) => {
      if (env.NEXT_PUBLIC_DOCS_VERSION !== "dev") {
        const require = createRequire(path.join(app, "package.json"));
        assert.deepEqual(
          JSON.parse(
            fs.readFileSync(
              require.resolve("@eneo/whats-new/releases.json"),
              "utf8",
            ),
          ),
          { releases: [] },
        );
      }
      exportPages(app);
    },
  });
});

test("publication digest changes for notes or release refs, not unrelated backend commits", (t) => {
  const f = fixture(t);
  f.git("add", ".");
  f.git("commit", "-m", "Development notes");
  const digest = () =>
    sourceDigest(f.repoRoot, resolveVersions({ repoRoot: f.repoRoot }));
  const original = digest();
  f.write("backend/example.py", "# unrelated");
  f.git("add", ".");
  f.git("commit", "-m", "Backend");
  assert.equal(digest(), original);
  f.write("frontend/packages/whats-new/releases.json", '{"releases":[]}');
  f.git("add", ".");
  f.git("commit", "-m", "Notes");
  assert.notEqual(digest(), original);
  const notes = digest();
  f.git("tag", "v2.2.0");
  assert.notEqual(digest(), notes);
});

test("authors cannot accidentally nest generated version folders in content", async (t) => {
  const f = fixture(t);
  f.write(
    "frontend/apps/docs-site/src/content/v2.1/index.mdx",
    "Wrong location",
  );
  await assert.rejects(
    buildSite({
      ...f,
      versions: resolveVersions({ repoRoot: f.repoRoot, only: "dev" }),
      build: async () => assert.fail("must reject before building"),
    }),
    /choose the release branch/,
  );
  assertUntouched(f);
});

test("the documentation builder works before the What’s new package is introduced", async (t) => {
  const f = fixture(t);
  fs.rmSync(f.packageDir, { recursive: true });
  fs.rmSync(path.join(f.appDir, "node_modules/@eneo"), { recursive: true });
  await buildSite({
    ...f,
    versions: resolveVersions({ repoRoot: f.repoRoot }),
    build: async (app) => {
      assert.equal(
        fs.existsSync(path.join(app, "node_modules/@eneo/whats-new")),
        false,
      );
      exportPages(app);
    },
  });
  assert.equal(
    fs.existsSync(path.join(f.appDir, "site/v2.1/index.html")),
    true,
  );
});

test("translations are selected with their ref in one build per version and receive stable aliases", async (t) => {
  const f = fixture(t);
  f.write(
    "frontend/apps/docs-site/src/content/sv/index.mdx",
    "Svensk utveckling",
  );
  f.git("add", ".");
  f.git("commit", "-m", "Translations in new release");
  f.git("tag", "v2.2.0");
  f.write(
    "frontend/apps/docs-site/src/content/sv/index.mdx",
    "Ny svensk utveckling",
  );
  const versions = resolveVersions({ repoRoot: f.repoRoot });
  const observed = [];
  await buildSite({
    ...f,
    versions,
    build: async (app, env) => {
      const translation = path.join(app, "src/content/sv/index.mdx");
      observed.push([
        env.NEXT_PUBLIC_DOCS_VERSION,
        fs.existsSync(translation)
          ? fs.readFileSync(translation, "utf8")
          : null,
      ]);
      exportPages(app);
      // The current renderer exports fallback routes even for English-only refs.
      fs.mkdirSync(path.join(app, "out/sv/guides"), { recursive: true });
      fs.writeFileSync(
        path.join(app, "out/sv.html"),
        "Swedish home or fallback",
      );
      fs.writeFileSync(
        path.join(app, "out/sv/guides/deployment.html"),
        "Swedish guide or fallback",
      );
    },
  });
  assert.deepEqual(observed, [
    ["v2.2", "Svensk utveckling"],
    ["v2.1", null],
    ["dev", "Ny svensk utveckling"],
  ]);
  assert.match(
    fs.readFileSync(
      path.join(f.appDir, "site/sv/guides/deployment.html"),
      "utf8",
    ),
    /\/v2\.2\/sv\/guides\/deployment/,
  );
  assert.match(
    fs.readFileSync(path.join(f.appDir, "site/sv.html"), "utf8"),
    /\/v2\.2\/sv/,
  );
});
