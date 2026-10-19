#!/usr/bin/env node
// Fails when the adapter-node server bundle imports a package instead of bundling it.
//
// The production image (frontend/Dockerfile) ships build/ and package.json without
// node_modules. adapter-node bundles devDependencies into build/ but leaves every package
// listed under `dependencies` as a bare import, which then throws ERR_MODULE_NOT_FOUND
// when a request first loads the page that uses it. Only Node built-ins may stay external.
//
// Runs after `vite build`; pass a build directory to check another output.

import { existsSync, readdirSync, statSync } from "node:fs";
import { isBuiltin } from "node:module";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const buildDir = resolve(appRoot, process.argv[2] ?? "build");

// build/client and build/prerendered are served to browsers, not loaded by Node.
const BROWSER_DIRS = new Set(["client", "prerendered"]);

function serverFiles(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (dir !== buildDir || !BROWSER_DIRS.has(entry)) files.push(...serverFiles(path));
    } else if (/\.(?:js|mjs|cjs)$/.test(entry)) {
      files.push(path);
    }
  }
  return files;
}

// An empty or relocated build would otherwise pass without checking anything.
if (!existsSync(join(buildDir, "handler.js"))) {
  console.error(`No adapter-node build at ${buildDir}; run vite build first.`);
  process.exit(1);
}

const files = serverFiles(buildDir);

// esbuild parses each file, so import-like text in comments and strings is not an import.
// Every package import stays external and is listed in the metafile; relative imports must
// resolve within build/.
const { metafile } = await build({
  entryPoints: files,
  absWorkingDir: buildDir,
  bundle: true,
  splitting: true,
  format: "esm",
  platform: "node",
  target: "esnext",
  packages: "external",
  outdir: join(buildDir, ".check-server-bundle"),
  write: false,
  metafile: true,
  logLevel: "error"
});

const problems = new Map();
for (const [input, { imports }] of Object.entries(metafile.inputs)) {
  for (const { path: specifier, external } of imports) {
    if (!external || isBuiltin(specifier)) continue;
    problems.set(specifier, [...(problems.get(specifier) ?? []), input]);
  }
}

if (problems.size > 0) {
  console.error(
    "The server bundle imports packages that the production image does not ship.\n" +
      "Move each package from `dependencies` to `devDependencies` in apps/web/package.json\n" +
      "so adapter-node bundles it into build/.\n"
  );
  for (const [specifier, importers] of problems) {
    console.error(`  ${specifier}`);
    for (const importer of importers) console.error(`    imported by ${importer}`);
  }
  process.exit(1);
}

console.log(
  `Server bundle is self-contained: ${files.length} files in ${relative(appRoot, buildDir)} ` +
    "import only Node built-ins."
);
