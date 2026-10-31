#!/usr/bin/env node
/**
 * Preserve Next source snapshots while routes move to TanStack. After porting
 * a page/layout, run --record src/app/<file>. When a recorded source changes,
 * port that change to its destination first, then --rerecord src/app/<file>.
 * Security sources use --record src/proxy.ts next.config.ts.
 *
 * Ordinary lint checks recorded sources and shared paths; --strict also requires
 * every Next page path and every page/layout snapshot. Path presence does not
 * prove equivalent loaders or UI: each route port still owns its behavior tests.
 * Delete this temporary migration check with Next in P6B.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const SECURITY_SOURCES = ["../proxy.ts", "../../next.config.ts"];
export const RETIRED_NEXT_ROUTES = new Map([
  ["/activate", "Next-only provisioning is retired; Vite serves signed-in not-found instead."]
]);
export const VITE_ONLY = new Map([
  ["/*", "Signed-in not-found splat (P4 router shell)."],
  ["/spaces/$/*", "Space-layout not-found splat (P4 gate pages)."],
  ["/logout", "Replaces the Next logout route handler."],
  ["/module-login", "Replaces the Next module-login route handler."],
  ["/login/switch-organisation", "Replaces the Next organisation-switch route handler."],
  ["/admin/federation", "Federation administration is exposed only in Vite."],
  ["/admin/user-groups", "Ports Svelte user-group administration, which had no Next page."]
]);

export function blobHash(bytes) {
  return createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
}

export function nextRoutePath(relDir) {
  const segments = relDir.split("/").filter((part) => part && !/^\(.*\)$/.test(part));
  return (
    "/" +
    segments
      .map((part) => {
        if (/^\[\[\.\.\.[^\]]+\]\]$/.test(part) || /^\[\.\.\.[^\]]+\]$/.test(part)) return "*";
        if (/^\[[^\]]+\]$/.test(part)) return "$";
        return part;
      })
      .join("/")
  );
}

export function viteRoutePaths(source) {
  const body = source.match(/\binterface FileRoutesByFullPath\s*\{([\s\S]*?)\n\}/)?.[1];
  if (body === undefined) throw new Error("Missing FileRoutesByFullPath declaration");
  const routes = body
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const route = line.match(/^\s*(['"])(\/.*?)\1\s*:/)?.[2];
      if (!route) throw new Error(`Unsupported FileRoutesByFullPath entry: ${line.trim()}`);
      return (
        "/" +
        route
          .split("/")
          .filter(Boolean)
          .map((part) => {
            if (part === "$" || /^\{-\$[^{}]+\}$/.test(part)) return "*";
            if (/[{}]/.test(part)) throw new Error(`Unsupported route brace syntax: ${route}`);
            return part.startsWith("$") ? "$" : part;
          })
          .join("/")
      );
    });
  return [...new Set(routes)];
}

export function parseLock(source) {
  const records = new Map();
  for (const [index, line] of source.split("\n").entries()) {
    if (!line) continue;
    const match = line.match(/^([0-9a-f]{40})  (\S(?:.*\S)?)$/);
    if (!match) throw new Error(`Malformed route-parity.lock line ${index + 1}`);
    const [, hash, file] = match;
    const hashes = records.get(file) ?? new Set();
    if (hashes.has(hash)) throw new Error(`Duplicate route-parity.lock record: ${file} ${hash}`);
    hashes.add(hash);
    records.set(file, hashes);
  }
  return records;
}

export function serializeLock(records) {
  return [...records.keys()]
    .sort()
    .flatMap((file) => [...records.get(file)].sort().map((hash) => `${hash}  ${file}\n`))
    .join("");
}

function pageRoute(file) {
  const directory = path.posix.dirname(file);
  return nextRoutePath(directory === "." ? "" : directory);
}

/** Pure comparison; files contains only exact page/layout names and security sources. */
export function checkParity(files, viteRoutes, records, strict = false) {
  const errors = [];
  const nextPages = new Set(
    [...files.keys()].filter((file) => path.posix.basename(file) === "page.tsx").map(pageRoute)
  );
  const vitePaths = new Set(viteRoutes);
  const unported = [...nextPages]
    .filter((route) => !vitePaths.has(route) && !RETIRED_NEXT_ROUTES.has(route))
    .sort();
  for (const [file, hashes] of records) {
    if (!files.has(file)) {
      errors.push(`Stale lock path (missing or not a page/layout/security source): ${file}`);
    } else if (!hashes.has(blobHash(files.get(file)))) {
      const destination = SECURITY_SOURCES.includes(file)
        ? "backend/src/eneo/server/web_app.py (CSP/path headers), middleware/response_headers.py (default headers), or the _app gate"
        : "the TanStack route and its feature owner";
      errors.push(
        `Drift: ${file}. Port the change to ${destination}, then run --rerecord for this file.`
      );
    }
  }
  for (const file of files.keys()) {
    if (SECURITY_SOURCES.includes(file)) continue;
    const sharedPage = path.posix.basename(file) === "page.tsx" && vitePaths.has(pageRoute(file));
    if (!records.has(file) && (strict || sharedPage))
      errors.push(`Unrecorded source: ${file}. Port it, then run --record.`);
  }
  for (const file of SECURITY_SOURCES) {
    if (!files.has(file)) errors.push(`Missing security source: ${file}`);
    else if (!records.has(file)) errors.push(`Unrecorded security source: ${file}`);
  }
  for (const route of vitePaths) {
    if (!nextPages.has(route) && !VITE_ONLY.has(route))
      errors.push(`Unknown Vite-only route: ${route}. Add its reviewed reason to VITE_ONLY.`);
  }
  if (strict) errors.push(...unported.map((route) => `Missing Vite route: ${route}`));
  return { errors, unported };
}

function sourceFiles(appDir) {
  const files = new Map();
  function visit(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile() && /^(page|layout)\.tsx$/.test(entry.name))
        files.set(path.relative(appDir, file), readFileSync(file));
    }
  }
  visit(appDir);
  for (const file of SECURITY_SOURCES) {
    if (existsSync(path.resolve(appDir, file)))
      files.set(file, readFileSync(path.resolve(appDir, file)));
  }
  return files;
}

export function main(args) {
  try {
    const root = fileURLToPath(new URL("../", import.meta.url));
    const appDir = path.join(root, "src/app");
    const lockPath = path.join(root, "scripts/route-parity.lock");
    const files = sourceFiles(appDir);
    const records = parseLock(existsSync(lockPath) ? readFileSync(lockPath, "utf8") : "");
    const [mode, ...requested] = args;
    if (mode === "--record" || mode === "--rerecord") {
      if (!requested.length) throw new Error(`${mode} needs at least one source file`);
      const paths = requested.map((file) => path.relative(appDir, path.resolve(root, file)));
      for (const file of paths) {
        if (!files.has(file))
          throw new Error(`Cannot record a missing or unsupported source: ${file}`);
      }
      for (const file of paths) {
        const hashes = mode === "--rerecord" ? new Set() : (records.get(file) ?? new Set());
        hashes.add(blobHash(files.get(file)));
        records.set(file, hashes);
      }
      writeFileSync(lockPath, serializeLock(records));
      return 0;
    }
    if (args.length && (mode !== "--strict" || args.length !== 1))
      throw new Error(
        "Usage: check-route-parity.mjs [--strict | --record <file>... | --rerecord <file>...]"
      );
    const routes = viteRoutePaths(readFileSync(path.join(root, "src/routeTree.gen.ts"), "utf8"));
    const { errors, unported } = checkParity(files, routes, records, mode === "--strict");
    if (unported.length)
      console.log(
        `Next routes not yet ported:\n${unported.map((route) => `  ${route}`).join("\n")}`
      );
    if (errors.length) console.error(errors.join("\n"));
    return errors.length ? 1 : 0;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main(process.argv.slice(2));
}
