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

const baseUrl = (process.env.ENEO_BACKEND_URL ?? "http://localhost:8123").replace(/\/$/, "");
const specUrl = `${baseUrl}/openapi.json`;
const outFile = "src/lib/api/schema.d.ts";

console.log(`Generating ${outFile} from ${specUrl}`);

// --default-non-nullable=false keeps properties that have defaults optional in
// request bodies (the backend fills them in); without it the generated types
// would force callers to pass every defaulted field.
run("node_modules/.bin/openapi-typescript", [
  specUrl,
  "-o",
  outFile,
  "--default-non-nullable=false"
]);
run("node_modules/.bin/prettier", ["--write", outFile]);

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
