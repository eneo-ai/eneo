#!/usr/bin/env node
/**
 * Regenerates src/lib/api/schema.d.ts from the backend's OpenAPI spec.
 *
 * The generated file is committed; CI regenerates it from the backend code
 * (app.openapi(), no running server) and fails on drift, so this script must
 * stay byte-compatible with the CI invocation: same openapi-typescript flags,
 * prettier-formatted output.
 *
 * Usage: bun run gen:api  (backend reachable at ENEO_BACKEND_URL, default
 * http://localhost:8123)
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const baseUrl = (process.env.ENEO_BACKEND_URL ?? "http://localhost:8123").replace(/\/$/, "");
const specUrl = `${baseUrl}/openapi.json`;
const outFile = "src/lib/api/schema.d.ts";

// The CLIs are resolved like imports, so they are found where the workspace
// install hoists them (frontend/node_modules), not only in this app's own
// node_modules/.bin.
const openapiTypescript = bin(
  require.resolve("openapi-typescript/package.json"),
  "openapi-typescript"
);
const prettier = bin(require.resolve("prettier/package.json"), "prettier");

console.log(`Generating ${outFile} from ${specUrl}`);

// --default-non-nullable=false keeps properties that have defaults optional in
// request bodies (the backend fills them in); without it the generated types
// would force callers to pass every defaulted field.
run(openapiTypescript, [specUrl, "-o", outFile, "--default-non-nullable=false"]);
run(prettier, ["--write", outFile]);

/** The path of a package's command-line entry, from its package.json `bin`. */
function bin(manifestPath, name) {
  const { bin: entries } = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entry = typeof entries === "string" ? entries : entries[name];
  return path.join(path.dirname(manifestPath), entry);
}

function run(script, args) {
  const result = spawnSync(process.execPath, [script, ...args], {
    cwd: appRoot,
    stdio: "inherit"
  });
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
